# -*- coding: utf-8 -*-  # Especifica codificación UTF-8 para caracteres especiales
"""Clasificador híbrido de incidentes: reglas + LLM con fusión segura.

Flujo:
    1. Clasificador por reglas (palabras clave, igual que el script base).
    2. Clasificador LLM (Ollama) que debe devolver un JSON exacto que se
       valida con pydantic; si el JSON es inválido se reintenta y después
       se cae al clasificador por reglas (plan de respaldo).
    3. Fusión: si ambos discrepan, prevalece la prioridad más alta
       (ante la duda, seguridad) y se marca requiere_revision_humana.
"""
import json  # Importa módulo json para parsear respuestas del LLM
import re  # Importa módulo re para expresiones regulares
import time  # Importa módulo time para medir latencia
import unicodedata  # Importa módulo unicodedata para normalizar texto

from pydantic import ValidationError  # Importa ValidationError para validar esquemas Pydantic

from . import llm  # Importa el módulo llm para interactuar con Ollama
from .esquemas import ClasificacionLLM  # Importa el esquema Pydantic para clasificación

# ---------------------------------------------------------------------------
# 1. CLASIFICADOR POR REGLAS (idéntico al script monolítico)
# ---------------------------------------------------------------------------

CATEGORIAS_KW = {  # Diccionario de categorías y sus palabras clave asociadas
    "materiales_peligrosos": ["peligroso", "derrame", "fuga", "quimico", "inflamable", "toxico", "corrosivo"],
    "sobrepeso": ["sobrepeso", "excede", "bascula", "exceso de peso", "sobrecarga"],
    "acceso_no_autorizado": ["sin autorizacion", "no autorizado", "acceso denegado", "barrera", "intruso"],
    "falla_hardware": ["camara", "sensor", "lector", "rfid", "no enciende", "apagado", "danado", "falla electrica"],
    "falla_software": ["sistema", "error", "pantalla", "caido", "no carga", "lento", "software", "aplicacion"],
    "somnolencia_conductor": ["somnolencia", "dormido", "cansancio", "fatiga", "sueno"],
}
PALABRAS_URGENTES = ["urgente", "emergencia", "accidente", "incendio", "herido", "critico", "inmediato"]  # Lista de palabras que indican urgencia
PRIORIDAD_BASE = {  # Diccionario de prioridades base por categoría
    "materiales_peligrosos": "critica",
    "somnolencia_conductor": "alta",
    "acceso_no_autorizado": "alta",
    "sobrepeso": "media",
    "falla_hardware": "media",
    "falla_software": "baja",
    "otro": "baja",
}
ORDEN_PRIORIDAD = ["baja", "media", "alta", "critica"]  # Lista ordenada de prioridades para comparación


def _normalizar(texto: str) -> str:  # Define función para normalizar texto (minúsculas sin acentos)
    """Minúsculas sin acentos ni ñ para comparar palabras clave."""
    texto = unicodedata.normalize("NFD", texto.lower())  # Normaliza a forma NFD y convierte a minúsculas
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")  # Elimina marcas diacríticas (acentos)


def clasificar_por_reglas(asunto: str, cuerpo: str) -> dict:  # Define función para clasificar por reglas
    """Categoría por conteo de palabras clave + escalado por urgencia."""
    texto = _normalizar(f"{asunto} {cuerpo}")  # Normaliza el texto completo (asunto + cuerpo)
    puntajes = {cat: [kw for kw in kws if kw in texto] for cat, kws in CATEGORIAS_KW.items()}  # Cuenta palabras clave por categoría
    mejor_cat = max(puntajes, key=lambda c: len(puntajes[c]))  # Selecciona la categoría con más coincidencias
    coincidencias = puntajes[mejor_cat]  # Obtiene las palabras clave que coincidieron
    if not coincidencias:  # Si no hubo coincidencias
        mejor_cat = "otro"  # Usa categoría por defecto "otro"

    prioridad = PRIORIDAD_BASE[mejor_cat]  # Obtiene la prioridad base de la categoría
    urgentes = [p for p in PALABRAS_URGENTES if p in texto]  # Busca palabras urgentes en el texto
    if urgentes:  # Si hay palabras urgentes
        idx = min(ORDEN_PRIORIDAD.index(prioridad) + 1, len(ORDEN_PRIORIDAD) - 1)  # Escala la prioridad un nivel
        prioridad = ORDEN_PRIORIDAD[idx]  # Actualiza la prioridad escalada

    return {"categoria": mejor_cat, "prioridad": prioridad,  # Retorna diccionario con categoría y prioridad
            "palabras_clave": coincidencias + urgentes}  # Incluye palabras clave encontradas


def extraer_datos(asunto: str, cuerpo: str) -> dict:  # Define función para extraer entidades con regex
    """Entidades por expresiones regulares (None si no se encuentran)."""
    texto = f"{asunto}\n{cuerpo}"  # Combina asunto y cuerpo en un solo texto
    m_placa = re.search(r"\b[A-Z0-9]{2,3}-\d{2,3}-[A-Z0-9]{1,2}\b", texto.upper())  # Busca placa con regex
    m_camion = re.search(r"\bCAM-\d+\b", texto.upper())  # Busca ID de camión con regex
    m_peso = re.search(r"(\d+(?:[.,]\d+)?)\s*(toneladas|tonelada|ton|t|kg)\b", texto.lower())  # Busca peso con regex
    peso_kg = None  # Inicializa peso en kg como None
    if m_peso:  # Si encontró peso
        valor = float(m_peso.group(1).replace(",", "."))  # Convierte el valor numérico a float
        peso_kg = valor if m_peso.group(2) == "kg" else valor * 1000  # Convierte a kg si está en toneladas
    m_ubic = re.search(r"\b(and[eé]n|puerta|muelle|caseta|dock)\s+([A-Za-z0-9]+)", texto, re.IGNORECASE)  # Busca ubicación
    return {  # Retorna diccionario con entidades extraídas
        "placa": m_placa.group(0) if m_placa else None,  # Placa o None
        "camion_id": m_camion.group(0) if m_camion else None,  # ID de camión o None
        "peso_reportado_kg": peso_kg,  # Peso en kg o None
        "ubicacion": f"{m_ubic.group(1)} {m_ubic.group(2)}".lower() if m_ubic else None,  # Ubicación o None
    }


# ---------------------------------------------------------------------------
# 2. CLASIFICADOR LLM (JSON estricto validado con pydantic + reintentos)
# ---------------------------------------------------------------------------

PROMPT_CLASIFICADOR = """Eres el clasificador de incidentes del centro logístico LogiSmart.
Analiza el correo y responde ÚNICAMENTE con un objeto JSON válido, sin texto
adicional, sin markdown, con EXACTAMENTE esta estructura:

{
  "categoria": "<una de: materiales_peligrosos | sobrepeso | acceso_no_autorizado | falla_hardware | falla_software | somnolencia_conductor | otro>",
  "prioridad": "<una de: baja | media | alta | critica>",
  "entidades": {
    "placa": "<placa vehicular o null>",
    "camion_id": "<id tipo CAM-### o null>",
    "peso_reportado_kg": <número en kg o null>,
    "ubicacion": "<lugar mencionado o null>"
  },
  "resumen": "<una frase corta describiendo el incidente>"
}

Reglas:
- materiales_peligrosos: derrames, fugas, químicos, inflamables, tóxicos.
- sobrepeso: exceso de peso en báscula, sobrecarga.
- acceso_no_autorizado: ingresos sin autorización, intrusos, barrera forzada.
- falla_hardware: cámaras, sensores, lectores RFID dañados o apagados.
- falla_software: sistema, aplicación, pantallas, errores de software.
- somnolencia_conductor: conductor dormido, fatiga, cansancio.
- prioridad critica: riesgo inmediato a personas o materiales peligrosos;
  alta: seguridad comprometida; media: operación afectada; baja: resto.
- Extrae solo datos presentes en el correo; si falta un dato usa null.
"""


def _parsear_json(texto: str) -> dict:  # Define función para parsear JSON con tolerancia a formato markdown
    """Tolera que el LLM envuelva el JSON en ```json ... ``` o texto extra."""
    limpio = texto.strip()  # Elimina espacios en blanco al inicio y final
    m = re.search(r"\{.*\}", limpio, re.DOTALL)  # Busca el objeto JSON en el texto
    if not m:  # Si no encuentra un objeto JSON
        raise ValueError("la respuesta no contiene un objeto JSON")  # Lanza error
    return json.loads(m.group(0))  # Parsea y retorna el JSON


def clasificar_llm(asunto: str, cuerpo: str, modelo: str,  # Define función para clasificar usando LLM
                   max_intentos: int = 2) -> dict:  # Parámetros: asunto, cuerpo, modelo, máximo de reintentos
    """Devuelve la clasificación del LLM validada con pydantic.

    Retorna {ok, datos, crudo, intentos, latencia_ms, error}.
    """
    if not llm.disponible():  # Verifica si Ollama está disponible
        return {"ok": False, "datos": None, "crudo": None, "intentos": 0,  # Retorna error si no está disponible
                "latencia_ms": 0, "error": "Ollama no disponible"}

    correo = f"ASUNTO: {asunto}\n\nCUERPO:\n{cuerpo}"  # Formatea el correo para enviar al LLM
    mensajes = [{"role": "system", "content": PROMPT_CLASIFICADOR},  # Mensaje del sistema con instrucciones
                {"role": "user", "content": correo}]  # Mensaje del usuario con el correo
    crudo, ultimo_error, latencia_total, intentos = None, None, 0, 0  # Inicializa variables de seguimiento

    for intento in range(1, max_intentos + 1):  # Itera hasta el máximo de intentos
        intentos = intento  # Registra el número de intento actual
        res = llm.chat(modelo, mensajes, json_mode=True)  # Llama al LLM en modo JSON
        latencia_total += res["latencia_ms"]  # Acumula la latencia
        if not res["ok"]:  # Si la llamada falló
            ultimo_error = res["error"]  # Almacena el error
            break  # Sale del bucle de reintentos
        crudo = res["contenido"]  # Almacena la respuesta cruda del LLM
        try:  # Intenta validar la respuesta con Pydantic
            datos = ClasificacionLLM.model_validate(_parsear_json(crudo))  # Valida con el esquema
            return {"ok": True, "datos": datos.model_dump(), "crudo": crudo,  # Retorna éxito con datos validados
                    "intentos": intentos, "latencia_ms": latencia_total, "error": None}
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:  # Si falla la validación
            ultimo_error = f"JSON inválido (intento {intento}): {exc}"  # Almacena el error
            mensajes.append({"role": "user", "content":  # Agrega mensaje de corrección para el siguiente intento
                             "Tu respuesta no fue un JSON válido con el esquema "
                             "requerido. Responde SOLO con el JSON correcto."})

    return {"ok": False, "datos": None, "crudo": crudo, "intentos": intentos,  # Retorna error después de agotar reintentos
            "latencia_ms": latencia_total, "error": ultimo_error}


# ---------------------------------------------------------------------------
# 3. FUSIÓN (híbrido)
# ---------------------------------------------------------------------------

def clasificar(asunto: str, cuerpo: str, modo: str = "hibrido",  # Define función principal de clasificación
               modelo: str = "llama3", max_intentos: int = 2) -> dict:  # Parámetros: modo (reglas|llm|hibrido), modelo, reintentos
    """Punto único de entrada. modo: reglas | llm | hibrido."""
    inicio = time.perf_counter()  # Inicia medición de tiempo
    reglas = clasificar_por_reglas(asunto, cuerpo)  # Ejecuta clasificador por reglas
    entidades_regex = extraer_datos(asunto, cuerpo)  # Extrae entidades con regex

    if modo == "reglas":  # Si el modo es solo reglas
        return {**reglas, "fuente": "reglas", "entidades": entidades_regex,  # Retorna resultado de reglas
                "requiere_revision_humana": False,  # No requiere revisión humana
                "latencia_ms": int((time.perf_counter() - inicio) * 1000),  # Calcula latencia
                "detalle": {"reglas": reglas}}  # Incluye detalle de reglas

    res_llm = clasificar_llm(asunto, cuerpo, modelo, max_intentos)  # Ejecuta clasificador LLM

    if modo == "llm":  # Si el modo es solo LLM
        if not res_llm["ok"]:  # Si el LLM falló
            # plan de respaldo: el LLM falló -> se entrega el clasificador por reglas
            return {**reglas, "fuente": "reglas (respaldo: LLM falló)",  # Retorna reglas como respaldo
                    "entidades": entidades_regex, "requiere_revision_humana": True,  # Marca para revisión humana
                    "latencia_ms": int((time.perf_counter() - inicio) * 1000),  # Calcula latencia
                    "error_llm": res_llm["error"], "detalle": {"reglas": reglas, "llm": res_llm}}  # Incluye error y detalles
        return {**res_llm["datos"], "fuente": "llm",  # Retorna datos del LLM si fue exitoso
                "requiere_revision_humana": False,  # No requiere revisión humana
                "latencia_ms": res_llm["latencia_ms"],  # Usa latencia del LLM
                "detalle": {"llm": res_llm}}  # Incluye detalle del LLM

    # ---- híbrido ----------------------------------------------------------
    if not res_llm["ok"]:  # Si en modo híbrido el LLM falló
        return {**reglas, "fuente": "reglas (respaldo: LLM no disponible)",  # Retorna reglas como respaldo
                "entidades": entidades_regex, "requiere_revision_humana": False,  # No marca para revisión (es respaldo)
                "latencia_ms": int((time.perf_counter() - inicio) * 1000),  # Calcula latencia
                "error_llm": res_llm["error"], "detalle": {"reglas": reglas, "llm": res_llm}}  # Incluye error y detalles

    cat_r, pri_r = reglas["categoria"], reglas["prioridad"]  # Obtiene categoría y prioridad de reglas
    datos_llm = res_llm["datos"]  # Obtiene datos del LLM
    cat_l, pri_l = datos_llm["categoria"], datos_llm["prioridad"]  # Obtiene categoría y prioridad del LLM

    # prioridad final = la más alta reportada (ante la duda, seguridad)
    prioridad = pri_r if ORDEN_PRIORIDAD.index(pri_r) >= ORDEN_PRIORIDAD.index(pri_l) else pri_l  # Elige la prioridad más alta
    # la categoría se toma del clasificador que reportó la prioridad mayor;
    # en empate se conserva la del LLM (entendió la semántica del correo)
    if ORDEN_PRIORIDAD.index(pri_r) > ORDEN_PRIORIDAD.index(pri_l):  # Si reglas tiene prioridad más alta
        categoria = cat_r  # Usa categoría de reglas
    else:  # Si LLM tiene prioridad igual o más alta
        categoria = cat_l  # Usa categoría del LLM
    revision = (cat_r != cat_l) or (pri_r != pri_l)  # Marca para revisión si hay discrepancia

    entidades = {k: v for k, v in datos_llm["entidades"].items() if v is not None}  # Extrae entidades no nulas del LLM
    for k, v in entidades_regex.items():  # regex como respaldo de campos nulos
        entidades.setdefault(k, v)  # Usa regex si el LLM devolvió null

    return {"categoria": categoria, "prioridad": prioridad,  # Retorna resultado fusionado
            "resumen": datos_llm.get("resumen", ""),  # Resumen del LLM
            "palabras_clave": reglas["palabras_clave"],  # Palabras clave de reglas
            "entidades": entidades,  # Entidades fusionadas
            "fuente": "hibrido",  # Marca fuente como híbrido
            "requiere_revision_humana": revision,  # Indica si requiere revisión
            "latencia_ms": int((time.perf_counter() - inicio) * 1000),  # Calcula latencia total
            "detalle": {"reglas": {"categoria": cat_r, "prioridad": pri_r},  # Detalle de reglas
                        "llm": {"categoria": cat_l, "prioridad": pri_l,  # Detalle del LLM
                                "intentos": res_llm["intentos"]}}}  # Incluye intentos del LLM


# ---------------------------------------------------------------------------
# 4. EVALUACIÓN CON DATASET ETIQUETADO
# ---------------------------------------------------------------------------

def evaluar_dataset(dataset: list, modelos_modos: list, modelo: str,  # Define función para evaluar clasificadores con dataset
                    max_intentos: int = 2, progreso=None) -> dict:  # Parámetros: dataset, modos a evaluar, modelo, reintentos, callback progreso
    """Corre el/los clasificadores sobre el dataset etiquetado.

    modelos_modos: subconjunto de ["reglas", "llm", "hibrido"].
    Devuelve métricas por modo: exactitud (categoría y prioridad), matriz de
    confusión de categorías y latencia promedio.
    """
    resultados = {m: {"aciertos_cat": 0, "aciertos_pri": 0, "latencias": [],  # Inicializa diccionario de resultados por modo
                      "matriz": {}, "detalle": []} for m in modelos_modos}  # Incluye aciertos, latencias, matriz y detalle
    total = len(dataset)  # Cuenta total de correos en el dataset

    for i, item in enumerate(dataset):  # Itera sobre cada correo del dataset
        for modo in modelos_modos:  # Itera sobre cada modo a evaluar
            r = clasificar(item["asunto"], item["cuerpo"], modo=modo,  # Clasifica el correo con el modo actual
                           modelo=modelo, max_intentos=max_intentos)  # Pasa modelo y reintentos
            acc = resultados[modo]  # Obtiene acumuladores para este modo
            ok_cat = r["categoria"] == item["categoria"]  # Verifica si la categoría es correcta
            ok_pri = r["prioridad"] == item["prioridad"]  # Verifica si la prioridad es correcta
            acc["aciertos_cat"] += ok_cat  # Incrementa contador de aciertos de categoría
            acc["aciertos_pri"] += ok_pri  # Incrementa contador de aciertos de prioridad
            acc["latencias"].append(r["latencia_ms"])  # Agrega latencia a la lista
            clave = f'{item["categoria"]} -> {r["categoria"]}'  # Crea clave para matriz de confusión
            acc["matriz"][clave] = acc["matriz"].get(clave, 0) + 1  # Incrementa contador en matriz de confusión
            acc["detalle"].append({"id": item.get("id", i + 1),  # Agrega detalle individual
                                   "esperada": item["categoria"],  # Categoría esperada
                                   "obtenida": r["categoria"],  # Categoría obtenida
                                   "prioridad_esperada": item["prioridad"],  # Prioridad esperada
                                   "prioridad_obtenida": r["prioridad"],  # Prioridad obtenida
                                   "correcto": ok_cat})  # Indica si fue correcto
        if progreso:  # Si se proporcionó callback de progreso
            progreso(i + 1, total)  # Llama al callback con progreso actual

    resumen = {}  # Inicializa diccionario de resumen
    for modo, acc in resultados.items():  # Itera sobre cada modo y sus acumuladores
        resumen[modo] = {  # Crea resumen para este modo
            "exactitud_categoria": round(acc["aciertos_cat"] / total, 4) if total else 0,  # Calcula exactitud de categoría
            "exactitud_prioridad": round(acc["aciertos_pri"] / total, 4) if total else 0,  # Calcula exactitud de prioridad
            "latencia_promedio_ms": int(sum(acc["latencias"]) / len(acc["latencias"])) if acc["latencias"] else 0,  # Calcula latencia promedio
            "matriz_confusion": acc["matriz"],  # Incluye matriz de confusión
            "detalle": acc["detalle"],  # Incluye detalle individual
        }
    return {"total_correos": total, "modos": modelos_modos, "resultados": resumen}  # Retorna resumen completo
