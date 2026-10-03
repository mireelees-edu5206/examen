# -*- coding: utf-8 -*-
"""Datos de demostración: camiones, accesos históricos, incidentes de
muestra y la matriz de riesgos éticos inicial. Idempotente: solo siembra
cuando la colección está vacía (o con forzar=True)."""
import random
from datetime import datetime, timedelta, timezone

from .clasificador import clasificar_por_reglas, extraer_datos
from .db import ahora_iso
from .reglas import evaluar_camion

CAMIONES_DEMO = [
    {"placa": "ABC-123-D", "camion_id": "CAM-101", "empresa": "Transportes del Norte",
     "autorizacion": True, "certificacion_vigente": True, "certificacion_dias_restantes": 240},
    {"placa": "XYZ-987-B", "camion_id": "CAM-102", "empresa": "Logística Química MX",
     "autorizacion": True, "certificacion_vigente": True, "certificacion_dias_restantes": 18},
    {"placa": "DEF-456-A", "camion_id": "CAM-103", "empresa": "Carga Pesada SA",
     "autorizacion": True, "certificacion_vigente": False, "certificacion_dias_restantes": 0},
    {"placa": "GHI-321-C", "camion_id": "CAM-104", "empresa": "Transportes del Norte",
     "autorizacion": False, "certificacion_vigente": True, "certificacion_dias_restantes": 120},
    {"placa": "JKL-654-E", "camion_id": "CAM-105", "empresa": "Materiales y Derivados",
     "autorizacion": True, "certificacion_vigente": True, "certificacion_dias_restantes": 25},
    {"placa": "MNO-789-F", "camion_id": "CAM-106", "empresa": "Logística Química MX",
     "autorizacion": True, "certificacion_vigente": True, "certificacion_dias_restantes": 300},
    {"placa": "PQR-112-G", "camion_id": "CAM-107", "empresa": "Carga Pesada SA",
     "autorizacion": True, "certificacion_vigente": True, "certificacion_dias_restantes": 60},
    {"placa": "STU-334-H", "camion_id": "CAM-108", "empresa": "Fletes Regionales",
     "autorizacion": False, "certificacion_vigente": False, "certificacion_dias_restantes": 0},
]

RIESGOS_DEMO = [
    {"modulo": "Clasificador híbrido (LLM)",
     "descripcion": "Alucinaciones del LLM: puede inventar una categoría o entidades "
                    "inexistentes cuando el correo es ambiguo.",
     "categoria": "transparencia", "probabilidad": 4, "impacto": 4,
     "mitigacion": "Salida JSON validada con pydantic, reintentos y plan de respaldo "
                   "por reglas; marcar requiere_revision_humana al discrepar.",
     "probabilidad_residual": 2, "impacto_residual": 3},
    {"modulo": "Clasificador por reglas",
     "descripcion": "Sesgo ante correos con ortografía informal, faltas o "
                    "regionalismos: palabras clave no coinciden y se subestima el incidente.",
     "categoria": "sesgo", "probabilidad": 4, "impacto": 3,
     "mitigacion": "Normalización de acentos, dataset con lenguaje informal real y "
                   "revisión humana obligatoria de la categoría 'otro'.",
     "probabilidad_residual": 3, "impacto_residual": 2},
    {"modulo": "Gestión de camiones",
     "descripcion": "Privacidad de datos del conductor: certificaciones y eventos de "
                    "somnolencia son datos personales sensibles almacenados en la BD.",
     "categoria": "privacidad", "probabilidad": 3, "impacto": 5,
     "mitigacion": "Mínimo de datos necesarios, control de acceso por rol, política "
                   "de retención y cifrado en reposo.",
     "probabilidad_residual": 2, "impacto_residual": 4},
    {"modulo": "Sistema completo",
     "descripcion": "Dependencia excesiva de la automatización: el operador deja de "
                    "verificar y acepta siempre la decisión del sistema.",
     "categoria": "responsabilidad", "probabilidad": 3, "impacto": 4,
     "mitigacion": "Explicación paso a paso obligatoria, bandera de revisión humana "
                   "y auditorías periódicas de decisiones.",
     "probabilidad_residual": 2, "impacto_residual": 3},
    {"modulo": "Asistente RAG",
     "descripcion": "Respuestas inventadas cuando no existen datos en la base "
                    "(falsa sensación de certeza para el operador).",
     "categoria": "transparencia", "probabilidad": 3, "impacto": 4,
     "mitigacion": "Patrón RAG estricto: consulta primero, respuesta solo con datos, "
                   "citas obligatorias y frase fija 'No tengo información'.",
     "probabilidad_residual": 2, "impacto_residual": 3},
    {"modulo": "Motor de reglas",
     "descripcion": "Regla nueva mal configurada (horario T o vigencia V) que bloquea "
                    "accesos legítimos o deja pasar carga peligrosa.",
     "categoria": "seguridad", "probabilidad": 2, "impacto": 4,
     "mitigacion": "Tablas de verdad verificables, análisis de redundancia/conflictos "
                   "y simulador para validar antes de aplicar.",
     "probabilidad_residual": 1, "impacto_residual": 3},
]


def _hace(dias: int, horas: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias, hours=horas)).isoformat(timespec="seconds")


def sembrar(store, correos: list = None, forzar: bool = False) -> dict:
    """Inserta datos de demostración. Devuelve conteos por colección."""
    resumen = {}

    # --- camiones ------------------------------------------------------------
    col = store.col("camiones")
    if forzar:
        col.vaciar()
    if col.contar() == 0:
        for c in CAMIONES_DEMO:
            col.insertar(c)
        resumen["camiones"] = len(CAMIONES_DEMO)

    # --- accesos históricos (últimos 21 días) ---------------------------------
    col = store.col("accesos")
    if forzar:
        col.vaciar()
    if col.contar() == 0:
        rng = random.Random(42)
        n = 0
        for cam in CAMIONES_DEMO:
            for _ in range(rng.randint(1, 3)):
                P = cam["autorizacion"]
                Q = rng.random() < 0.2
                R = "Química" in cam["empresa"] or rng.random() < 0.15
                S = cam["certificacion_vigente"]
                T = rng.random() < 0.25
                V = cam["certificacion_dias_restantes"] < 30
                res = evaluar_camion(P, Q, R, S, T, V)
                col.insertar({"camion_id": cam["camion_id"], "placa": cam["placa"],
                              "P": P, "Q": Q, "R": R, "S": S, "T": T, "V": V,
                              "A": res["A"], "E": res["E"], "H": res["H"], "W": res["W"],
                              "decision": res["decision"], "semaforo": res["semaforo"],
                              "explicacion": res["explicacion"],
                              "operador": "demo", "timestamp": _hace(rng.randint(0, 21), rng.randint(0, 14))})
                n += 1
        resumen["accesos"] = n

    # --- incidentes de muestra (derivados del dataset etiquetado) -------------
    col = store.col("incidentes")
    if forzar:
        col.vaciar()
    if col.contar() == 0 and correos:
        rng = random.Random(7)
        estados = ["nuevo", "en_atencion", "cerrado", "cerrado", "nuevo"]
        n = 0
        for item in rng.sample(correos, min(14, len(correos))):
            c = clasificar_por_reglas(item["asunto"], item["cuerpo"])
            col.insertar({
                "remitente": item.get("remitente", "operador@planta.local"),
                "asunto": item["asunto"], "cuerpo": item["cuerpo"],
                "clasificacion": {**c, "fuente": "reglas (demo)"},
                "datos_extraidos": extraer_datos(item["asunto"], item["cuerpo"]),
                "estado": rng.choice(estados),
                "requiere_revision_humana": False,
                "timestamp": _hace(rng.randint(0, 28), rng.randint(0, 20)),
                "historial": [{"ts": _hace(rng.randint(0, 2)), "evento": "creado por seed"}],
            })
            n += 1
        resumen["incidentes"] = n

    # --- riesgos éticos ---------------------------------------------------------
    col = store.col("riesgos_eticos")
    if forzar:
        col.vaciar()
    if col.contar() == 0:
        for r in RIESGOS_DEMO:
            col.insertar({**r, "historico": [{"ts": ahora_iso(), "evento": "alta (seed)"}]})
        resumen["riesgos_eticos"] = len(RIESGOS_DEMO)

    # --- marca de semilla --------------------------------------------------------
    store.col("meta").insertar({"_tipo": "seed", "ts": ahora_iso(), "resumen": resumen})
    return resumen
