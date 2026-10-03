# -*- coding: utf-8 -*-
"""API núcleo: estado del sistema, dashboard, configuración, seed y reportes."""
from collections import Counter

from flask import Blueprint, Response, jsonify, request

from .. import get_store, cargar_dataset, llm
from ..db import ahora_iso
from ..reportes import a_csv, a_json, nombre_archivo
import config as cfg

api_nucleo = Blueprint("api_nucleo", __name__, url_prefix="/api")


def _modelo_actual(store) -> str:
    return store.obtener_config().get("modelo") or cfg.MODELO_DEFAULT


@api_nucleo.get("/estado")
def estado():
    store = get_store()
    return jsonify({"persistencia": store.estado(),
                    "ollama": {"disponible": llm.disponible(),
                               "modelos": llm.listar_modelos(),
                               "modelo_actual": _modelo_actual(store)},
                    "config": store.obtener_config()})


@api_nucleo.get("/dashboard")
def dashboard():
    store = get_store()
    desde, hasta = request.args.get("desde"), request.args.get("hasta")

    filtro = {}
    if desde:
        filtro["timestamp"] = {"$gte": desde}
    if hasta:
        filtro.setdefault("timestamp", {})["$lte"] = hasta + "T23:59:59"

    accesos = store.col("accesos").buscar(filtro, orden=[("timestamp", -1)])
    incidentes = store.col("incidentes").buscar(filtro, orden=[("timestamp", -1)])
    riesgos = store.col("riesgos_eticos").buscar()

    por_decision = Counter(a.get("decision", "?") for a in accesos)
    por_categoria = Counter(i.get("clasificacion", {}).get("categoria", "otro")
                            for i in incidentes)
    por_prioridad = Counter(i.get("clasificacion", {}).get("prioridad", "baja")
                            for i in incidentes)

    riesgos_criticos = [r for r in riesgos
                        if r.get("probabilidad", 1) * r.get("impacto", 1) >= 17]

    return jsonify({
        "kpis": {
            "camiones_atendidos": len(accesos),
            "incidentes_abiertos": sum(1 for i in incidentes
                                       if i.get("estado") in ("nuevo", "en_atencion")),
            "incidentes_total": len(incidentes),
            "riesgos_criticos": len(riesgos_criticos),
            "camiones_registrados": store.col("camiones").contar(),
        },
        "graficas": {
            "accesos_decision": dict(por_decision),
            "incidentes_categoria": dict(por_categoria),
            "incidentes_prioridad": dict(por_prioridad),
            "incidentes_semana": store.incidentes_por_categoria_semana(),
        },
        "ultimos_accesos": accesos[:8],
        "motor": store.motor,
    })


@api_nucleo.get("/incidentes/agregacion")
def agregacion():
    """Incidentes agrupados por categoría y semana ISO."""
    return jsonify(get_store().incidentes_por_categoria_semana())


@api_nucleo.route("/config", methods=["GET", "PUT"])
def configuracion():
    store = get_store()
    if request.method == "GET":
        return jsonify(store.obtener_config())
    datos = request.get_json(force=True, silent=True) or {}
    permitidos = {"modelo", "umbral_confianza", "simulacion_correo", "operador"}
    campos = {k: v for k, v in datos.items() if k in permitidos}
    if "umbral_confianza" in campos:
        try:
            campos["umbral_confianza"] = max(0.0, min(1.0, float(campos["umbral_confianza"])))
        except (TypeError, ValueError):
            return jsonify({"error": "umbral_confianza debe ser un número entre 0 y 1"}), 400
    if campos:
        store.guardar_config(campos)
    return jsonify(store.obtener_config())


@api_nucleo.post("/seed")
def seed():
    store = get_store()
    forzar = request.args.get("forzar") == "1"
    from ..seed import sembrar
    resumen = sembrar(store, cargar_dataset(), forzar=forzar)
    return jsonify({"ok": True, "sembrado": resumen, "motor": store.motor})


@api_nucleo.post("/reconectar")
def reconectar():
    store = get_store()
    ok = store.reconectar()
    return jsonify({"conectado": ok, "estado": store.estado()})


COLECCIONES_EXPORTABLES = {"camiones", "accesos", "incidentes",
                           "riesgos_eticos", "evaluaciones_llm"}


@api_nucleo.get("/reportes/<coleccion>/<formato>")
def reporte(coleccion, formato):
    if coleccion not in COLECCIONES_EXPORTABLES:
        return jsonify({"error": "colección no exportable"}), 404
    docs = get_store().col(coleccion).buscar(orden=[("timestamp", -1)])
    if coleccion == "riesgos_eticos":
        docs = sorted(docs, key=lambda d: str(d.get("creado_en", "")), reverse=True)

    if formato == "csv":
        return Response(a_csv(docs), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f"attachment; filename={nombre_archivo(coleccion, 'csv')}"})
    if formato == "json":
        return Response(a_json(docs), mimetype="application/json; charset=utf-8",
                        headers={"Content-Disposition":
                                 f"attachment; filename={nombre_archivo(coleccion, 'json')}"})
    if formato == "datos":  # JSON embebido para el PDF del lado cliente
        return jsonify({"coleccion": coleccion, "generado": ahora_iso(), "datos": docs})
    return jsonify({"error": "formato no soportado (csv|json)"}), 404
