# -*- coding: utf-8 -*-
"""API de incidentes: clasificación (reglas/LLM/híbrido), CRUD, cambio de
estado con historial, y evaluación del dataset etiquetado en segundo plano."""
import threading
import uuid

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from .. import get_store, cargar_dataset, clasificador
from ..db import ahora_iso
from ..esquemas import ClasificarIn, IncidenteUpdate
import config as cfg

api_incidentes = Blueprint("api_incidentes", __name__, url_prefix="/api")

EVAL_JOB = {"corriendo": False, "progreso": 0, "total": 0,
            "resultado": None, "error": None}


def _modelo_actual(store) -> str:
    return store.obtener_config().get("modelo") or cfg.MODELO_DEFAULT


def _doc_incidente(datos: ClasificarIn, resultado: dict) -> dict:
    return {"remitente": datos.remitente, "asunto": datos.asunto,
            "cuerpo": datos.cuerpo,
            "clasificacion": {k: resultado.get(k) for k in
                              ("categoria", "prioridad", "resumen", "fuente",
                               "palabras_clave", "detalle", "error_llm")
                              if resultado.get(k) is not None},
            "datos_extraidos": resultado.get("entidades", {}),
            "estado": "nuevo",
            "requiere_revision_humana": resultado.get("requiere_revision_humana", False),
            "timestamp": ahora_iso(),
            "historial": [{"ts": ahora_iso(),
                           "evento": f"clasificado por {resultado.get('fuente')}"}]}


@api_incidentes.post("/incidentes/clasificar")
def clasificar():
    store = get_store()
    try:
        datos = ClasificarIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400

    resultado = clasificador.clasificar(
        datos.asunto, datos.cuerpo, modo=datos.modo,
        modelo=_modelo_actual(store), max_intentos=cfg.LLM_MAX_INTENTOS)
    if datos.guardar:
        doc = _doc_incidente(datos, resultado)
        doc["_id"] = store.col("incidentes").insertar(doc)
        resultado["incidente"] = doc
    return jsonify(resultado)


@api_incidentes.route("/incidentes", methods=["GET", "POST"])
def incidentes():
    store = get_store()
    col = store.col("incidentes")
    if request.method == "GET":
        filtro = {}
        if request.args.get("estado"):
            filtro["estado"] = request.args["estado"]
        if request.args.get("categoria"):
            filtro["clasificacion.categoria"] = request.args["categoria"]
        if request.args.get("revision") == "1":
            filtro["requiere_revision_humana"] = True
        limite = min(int(request.args.get("limite", 200)), 500)
        return jsonify(col.buscar(filtro, orden=[("timestamp", -1)], limite=limite))

    try:
        datos = ClasificarIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400
    resultado = clasificador.clasificar(
        datos.asunto, datos.cuerpo, modo=datos.modo,
        modelo=_modelo_actual(store), max_intentos=cfg.LLM_MAX_INTENTOS)
    doc = _doc_incidente(datos, resultado)
    doc["_id"] = col.insertar(doc)
    return jsonify(doc), 201


@api_incidentes.route("/incidentes/<doc_id>", methods=["GET", "PUT", "DELETE"])
def incidente_detalle(doc_id):
    store = get_store()
    col = store.col("incidentes")
    doc = col.buscar_por_id(doc_id)
    if not doc:
        return jsonify({"error": "no encontrado"}), 404

    if request.method == "GET":
        return jsonify(doc)
    if request.method == "DELETE":
        col.eliminar(doc_id)
        return jsonify({"ok": True})

    try:
        datos = IncidenteUpdate.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400
    cambios, eventos = {}, []
    if datos.estado and datos.estado != doc.get("estado"):
        cambios["estado"] = datos.estado
        eventos.append(f"estado: {doc.get('estado')} -> {datos.estado}")
    for campo in ("categoria", "prioridad"):
        nuevo = getattr(datos, campo)
        if nuevo and nuevo != doc.get("clasificacion", {}).get(campo):
            cambios[f"clasificacion.{campo}"] = nuevo
            eventos.append(f"{campo} corregida manualmente -> {nuevo}")
    if datos.nota:
        eventos.append(f"nota: {datos.nota}")
    if cambios:
        # campos anidados: actualizar el dict completo para el almacén local
        if "clasificacion.categoria" in cambios or "clasificacion.prioridad" in cambios:
            clasif = dict(doc.get("clasificacion", {}))
            clasif["categoria"] = datos.categoria or clasif.get("categoria")
            clasif["prioridad"] = datos.prioridad or clasif.get("prioridad")
            cambios = {"estado": cambios.get("estado", doc.get("estado")),
                       "clasificacion": clasif}
        col.actualizar(doc_id, cambios)
    for ev in eventos:
        col.agregar_a_lista(doc_id, "historial", {"ts": ahora_iso(), "evento": ev})
    return jsonify(col.buscar_por_id(doc_id))


# ------------------------------------------------------------ evaluación
def _trabajar_evaluacion(store, modos, modelo):
    EVAL_JOB.update({"corriendo": True, "progreso": 0, "error": None,
                     "resultado": None})
    try:
        dataset = cargar_dataset()
        EVAL_JOB["total"] = len(dataset) * len(modos)

        # progreso por correo procesado (cada correo ejecuta len(modos) clasificaciones)
        def avance(i, total):
            EVAL_JOB["progreso"] = i * len(modos)

        resultado = clasificador.evaluar_dataset(
            dataset, modos, modelo, cfg.LLM_MAX_INTENTOS, progreso=avance)

        run_id = uuid.uuid4().hex[:12]
        col = store.col("evaluaciones_llm")
        for modo, acc in resultado["resultados"].items():
            col.insertar({
                "run_id": run_id, "modo": modo, "modelo": modelo,
                "prompt": "dataset correos_etiquetados.json",
                "respuesta": {"exactitud_categoria": acc["exactitud_categoria"],
                              "exactitud_prioridad": acc["exactitud_prioridad"],
                              "matriz_confusion": acc["matriz_confusion"]},
                "latencia": acc["latencia_promedio_ms"],
                "coincidio_reglas": acc["exactitud_categoria"],
                "total_correos": resultado["total_correos"],
                "timestamp": ahora_iso()})
        EVAL_JOB["resultado"] = resultado
    except Exception as exc:
        EVAL_JOB["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        EVAL_JOB["corriendo"] = False


@api_incidentes.post("/evaluacion/ejecutar")
def evaluacion_ejecutar():
    if EVAL_JOB["corriendo"]:
        return jsonify({"error": "Ya hay una evaluación en curso"}), 409
    datos = request.get_json(force=True, silent=True) or {}
    modos = [m for m in datos.get("modos", ["reglas", "llm", "hibrido"])
             if m in ("reglas", "llm", "hibrido")] or ["reglas"]
    store = get_store()
    EVAL_JOB.update({"corriendo": True, "progreso": 0,
                     "total": len(cargar_dataset()) * len(modos),
                     "resultado": None, "error": None})
    hilo = threading.Thread(target=_trabajar_evaluacion,
                            args=(store, modos, _modelo_actual(store)), daemon=True)
    hilo.start()
    return jsonify({"ok": True, "total": EVAL_JOB["total"]})


@api_incidentes.get("/evaluacion/estado")
def evaluacion_estado():
    return jsonify(EVAL_JOB)


@api_incidentes.get("/evaluacion/historico")
def evaluacion_historico():
    docs = get_store().col("evaluaciones_llm").buscar(orden=[("timestamp", -1)], limite=40)
    return jsonify(docs)
