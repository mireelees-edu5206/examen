# -*- coding: utf-8 -*-  # Especifica codificación UTF-8 para caracteres especiales
"""Asistente explicativo con patrón RAG sencillo.

    pregunta -> recuperar de MongoDB -> construir contexto -> LLM responde
    SOLO con lo recuperado, citando los registros de origen. Si no hay
    datos, responde "No tengo información" (sin inventar). Si el LLM no
    está disponible, responde con una plantilla determinista.
"""
import re  # Importa módulo re para expresiones regulares

from . import llm  # Importa el módulo llm para interactuar con Ollama
from .db import ahora_iso  # Importa la función para generar timestamps

MAX_DOCS_CONTEXTO = 8  # Define el máximo de documentos a incluir en el contexto del LLM


def _buscar_referencias(pregunta: str, store) -> list:  # Define función para buscar documentos relevantes según la pregunta
    """Recupera los documentos relevantes de MongoDB para la pregunta.

    Devuelve lista de {"coleccion", "id", "resumen", "doc"}.
    """
    hallados = []  # Inicializa lista para almacenar documentos encontrados
    texto = pregunta.upper()  # Convierte la pregunta a mayúsculas para búsqueda case-insensitive

    ids_camion = set(re.findall(r"\bCAM-?\s?(\d+)\b", texto))  # Extrae IDs de camión (CAM-###) usando regex
    ids_camion = {f"CAM-{n}" for n in ids_camion}  # Formatea los IDs con el prefijo CAM-
    placas = set(re.findall(r"\b[A-Z0-9]{2,3}-\d{2,3}-[A-Z0-9]{1,2}\b", texto))  # Extrae placas usando regex

    # --- búsqueda por camión / placa ----------------------------------------
    if ids_camion or placas:  # Si se encontraron IDs de camión o placas
        camiones = store.col("camiones").buscar()  # Busca todos los camiones en la base de datos
        objetivos = [c for c in camiones  # Filtra camiones que coinciden con ID o placa
                     if c.get("camion_id") in ids_camion or c.get("placa") in placas]
        for cam in objetivos:  # Itera sobre los camiones encontrados
            cid = cam.get("camion_id")  # Obtiene el ID del camión
            hallados.append({"coleccion": "camiones", "id": str(cam.get("_id")),  # Agrega información del camión
                             "resumen": f"{cid} placa {cam.get('placa')} empresa {cam.get('empresa')}",
                             "doc": cam})
            accesos_camion = (store.col("accesos").buscar({"camion_id": cid},  # Busca accesos por ID de camión
                              orden=[("timestamp", -1)], limite=3) +  # Obtiene los 3 más recientes
                              store.col("accesos").buscar({"placa": cam.get("placa")},  # También busca por placa
                              orden=[("timestamp", -1)], limite=3))  # Obtiene los 3 más recientes
            for acc in accesos_camion[:3]:  # Itera sobre los primeros 3 accesos
                hallados.append({"coleccion": "accesos", "id": str(acc.get("_id")),  # Agrega información del acceso
                                 "resumen": f"acceso {acc.get('timestamp','?')[:16]}: {acc.get('decision')}",
                                 "doc": acc})
            for inc in store.col("incidentes").buscar(limite=400):  # Busca incidentes (hasta 400)
                datos = inc.get("datos_extraidos", {}) or {}  # Obtiene datos extraídos del incidente
                if datos.get("camion_id") == cid or datos.get("placa") == cam.get("placa"):  # Si coincide con camión
                    hallados.append({"coleccion": "incidentes", "id": str(inc.get("_id")),  # Agrega información del incidente
                                     "resumen": f"incidente {inc.get('clasificacion',{}).get('categoria')} "
                                                f"estado {inc.get('estado')}",
                                     "doc": inc})

    # --- intenciones generales ------------------------------------------------
    if re.search(r"incidente|correo|reporte", pregunta, re.IGNORECASE):  # Si pregunta sobre incidentes o reportes
        if re.search(r"abierto|pendiente|nuevo|en_atencion|en atencion", pregunta, re.IGNORECASE):  # Si pregunta sobre abiertos
            docs = store.col("incidentes").buscar(  # Busca incidentes con estado nuevo o en atención
                {"estado": {"$in": ["nuevo", "en_atencion"]}},
                orden=[("timestamp", -1)], limite=MAX_DOCS_CONTEXTO)  # Ordenados por fecha, máximo 8
        else:  # Si pregunta sobre incidentes en general
            docs = store.col("incidentes").buscar(  # Busca todos los incidentes
                orden=[("timestamp", -1)], limite=MAX_DOCS_CONTEXTO)  # Ordenados por fecha, máximo 8
        for d in docs:  # Itera sobre los incidentes encontrados
            hallados.append({"coleccion": "incidentes", "id": str(d.get("_id")),  # Agrega información del incidente
                             "resumen": f"{d.get('clasificacion',{}).get('categoria')} "
                                        f"({d.get('clasificacion',{}).get('prioridad')}) "
                                        f"estado {d.get('estado')} - {d.get('asunto','')[:60]}",
                             "doc": d})

    if re.search(r"acceso|camion|camiones|entr[oó]|ingres", pregunta, re.IGNORECASE) and not ids_camion:  # Si pregunta sobre accesos/camiones pero no específico
        for d in store.col("accesos").buscar(orden=[("timestamp", -1)], limite=5):  # Busca los 5 accesos más recientes
            hallados.append({"coleccion": "accesos", "id": str(d.get("_id")),  # Agrega información del acceso
                             "resumen": f"{d.get('camion_id') or d.get('placa')} -> "
                                        f"{d.get('decision')} ({d.get('timestamp','')[:16]})",
                             "doc": d})
        for d in store.col("camiones").buscar(limite=20):  # Busca camiones (hasta 20)
            if re.search(r"cu[aá]ntos|lista|todos", pregunta, re.IGNORECASE):  # Si pregunta por conteo o lista
                hallados.append({"coleccion": "camiones", "id": str(d.get("_id")),  # Agrega información del camión
                                 "resumen": f"{d.get('camion_id')} {d.get('placa')} {d.get('empresa')}",
                                 "doc": d})
                break  # Basta con uno para el conteo

    if re.search(r"riesgo|[ée]tic", pregunta, re.IGNORECASE):  # Si pregunta sobre riesgos o ética
        docs = store.col("riesgos_eticos").buscar()  # Busca todos los riesgos éticos
        docs.sort(key=lambda d: d.get("probabilidad", 1) * d.get("impacto", 1), reverse=True)  # Ordena por riesgo (P*I)
        for d in docs[:MAX_DOCS_CONTEXTO]:  # Itera sobre los primeros 8 riesgos
            hallados.append({"coleccion": "riesgos_eticos", "id": str(d.get("_id")),  # Agrega información del riesgo
                             "resumen": f"[{d.get('categoria')}] {d.get('descripcion','')[:70]} "
                                        f"P{d.get('probabilidad')}xI{d.get('impacto')}",
                             "doc": d})

    # deduplicar por (coleccion, id)
    vistos, unicos = set(), []  # Inicializa conjunto de vistos y lista de únicos
    for h in hallados:  # Itera sobre los documentos hallados
        clave = (h["coleccion"], h["id"])  # Crea clave única por colección e ID
        if clave not in vistos:  # Si no se ha visto esta clave
            vistos.add(clave)  # Agrega al conjunto de vistos
            unicos.append(h)  # Agrega a la lista de únicos
    return unicos[:MAX_DOCS_CONTEXTO]  # Retorna los primeros 8 documentos únicos


def _contexto(hallados: list) -> str:  # Define función para serializar documentos como contexto para el LLM
    """Serializa los documentos recuperados como contexto para el LLM."""
    lineas = []  # Inicializa lista de líneas para el contexto
    for h in hallados:  # Itera sobre los documentos hallados
        d = h["doc"]  # Obtiene el documento completo
        partes = [f"[{h['coleccion']}#{h['id']}]"]  # Inicializa partes con etiqueta de colección e ID
        if h["coleccion"] == "accesos":  # Si es un acceso
            partes.append(f"camion={d.get('camion_id')} placa={d.get('placa')} "  # Agrega datos del camión
                          f"P={d.get('P')} Q={d.get('Q')} R={d.get('R')} S={d.get('S')} "  # Agrega premisas P,Q,R,S
                          f"T={d.get('T')} V={d.get('V')} "  # Agrega premisas T,V
                          f"decision={d.get('decision')} fecha={d.get('timestamp','')[:16]}")  # Agrega decisión y fecha
            pasos = d.get("explicacion") or []  # Obtiene la explicación del razonamiento
            if pasos:  # Si hay pasos de explicación
                partes.append("razonamiento: " + " | ".join(pasos[-4:]))  # Agrega los últimos 4 pasos
        elif h["coleccion"] == "incidentes":  # Si es un incidente
            c = d.get("clasificacion", {})  # Obtiene la clasificación del incidente
            partes.append(f"asunto={d.get('asunto','')} categoria={c.get('categoria')} "  # Agrega asunto y categoría
                          f"prioridad={c.get('prioridad')} estado={d.get('estado')} "  # Agrega prioridad y estado
                          f"fecha={d.get('timestamp','')[:16]}")  # Agrega fecha
        elif h["coleccion"] == "camiones":  # Si es un camión
            partes.append(f"camion_id={d.get('camion_id')} placa={d.get('placa')} "  # Agrega ID y placa
                          f"empresa={d.get('empresa')} autorizacion={d.get('autorizacion')} "  # Agrega empresa y autorización
                          f"certificacion_vigente={d.get('certificacion_vigente')} "  # Agrega estado de certificación
                          f"dias_cert={d.get('certificacion_dias_restantes')}")  # Agrega días restantes de certificación
        else:  # Para cualquier otra colección (riesgos, etc.)
            partes.append(f"modulo={d.get('modulo')} categoria={d.get('categoria')} "  # Agrega módulo y categoría
                          f"descripcion={d.get('descripcion')} "  # Agrega descripción
                          f"probabilidad={d.get('probabilidad')} impacto={d.get('impacto')} "  # Agrega probabilidad e impacto
                          f"mitigacion={d.get('mitigacion','')}")  # Agrega mitigación
        lineas.append(" ".join(partes))  # Une las partes y agrega a la lista de líneas
    return "\n".join(lineas)  # Retorna las líneas unidas con saltos de línea


PROMPT_ASISTENTE = """Eres el asistente del centro de control LogiSmart.
Responde la pregunta del operador usando EXCLUSIVAMENTE la información del
CONTEXTO (registros reales de la base de datos).

Reglas estrictas:
1. Cita siempre el registro de origen con su etiqueta, p. ej. [accesos#abc123].
2. Si el contexto NO contiene la respuesta, di exactamente:
   "No tengo información registrada sobre eso." No inventes datos.
3. Responde en español, claro y breve (máximo 3 párrafos cortos o viñetas).
4. Cuando expliques una decisión de acceso, menciona las premisas (P,Q,R,S,T,V)
   que la causaron según el razonamiento registrado.
"""


def responder(pregunta: str, store, modelo: str, sid: str = "") -> dict:  # Define función principal para responder preguntas
    hallados = _buscar_referencias(pregunta, store)  # Busca documentos relevantes según la pregunta
    fuentes = [{"coleccion": h["coleccion"], "id": h["id"], "resumen": h["resumen"]}  # Extrae fuentes de los hallados
               for h in hallados]

    if not hallados:  # Si no se encontraron documentos
        respuesta = ("No tengo información registrada sobre eso. "  # Respuesta por defecto cuando no hay datos
                     "Puedo consultar camiones por placa o ID (CAM-###), "
                     "accesos recientes, incidentes y la matriz de riesgos.")
        modo = "sin_datos"  # Marca el modo como sin datos
    else:  # Si se encontraron documentos
        contexto = _contexto(hallados)  # Genera el contexto a partir de los documentos hallados
        res = llm.chat(modelo, [  # Llama al LLM con el contexto y la pregunta
            {"role": "system", "content": PROMPT_ASISTENTE},  # Mensaje del sistema con instrucciones
            {"role": "user", "content": f"CONTEXTO:\n{contexto}\n\nPREGUNTA: {pregunta}"},  # Mensaje del usuario
        ])
        if res["ok"]:  # Si la llamada al LLM fue exitosa
            respuesta = res["contenido"]  # Usa la respuesta del LLM
            modo = "llm"  # Marca el modo como LLM
        else:  # Si falló la llamada al LLM
            # Respaldo determinista cuando Ollama no está disponible
            respuesta = ("(LLM no disponible; respuesta generada solo con datos "  # Respuesta de respaldo
                         "recuperados)\n\n" +
                         "\n".join(f"- {h['resumen']}  [{h['coleccion']}#{h['id'}]"  # Lista resúmenes con referencias
                                   for h in hallados))
            modo = "reglas"  # Marca el modo como reglas (respaldo)

    store.col("conversaciones").insertar(  # Guarda la conversación en la base de datos
        {"sid": sid, "pregunta": pregunta, "respuesta": respuesta,  # Almacena sesión, pregunta y respuesta
         "fuentes": fuentes, "modo": modo, "timestamp": ahora_iso()})  # Almacena fuentes, modo y timestamp
    return {"respuesta": respuesta, "fuentes": fuentes, "modo": modo}  # Retorna respuesta, fuentes y modo
