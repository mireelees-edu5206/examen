# -*- coding: utf-8 -*-
"""API del asistente explicativo (RAG sobre MongoDB)."""
import uuid

from flask import Blueprint, jsonify, request, session

from .. import get_store, asistente
import config as cfg

api_asistente = Blueprint("api_asistente", __name__, url_prefix="/api/asistente")


@api_asistente.post("/preguntar")
def preguntar():
    store = get_store()
    datos = request.get_json(force=True, silent=True) or {}
    pregunta = (datos.get("pregunta") or "").strip()
    if not pregunta:
        return jsonify({"error": "Escribe una pregunta."}), 400
    if len(pregunta) > 2000:
        return jsonify({"error": "Pregunta demasiado larga (máx. 2000)."}), 400
    session.setdefault("sid", uuid.uuid4().hex)
    modelo = store.obtener_config().get("modelo") or cfg.MODELO_DEFAULT
    res = asistente.responder(pregunta, store, modelo, session["sid"])
    return jsonify(res)


@api_asistente.get("/historial")
def historial():
    store = get_store()
    sid = session.get("sid", "")
    docs = store.col("conversaciones").buscar({"sid": sid},
                                              orden=[("timestamp", -1)], limite=30)
    return jsonify(list(reversed(docs)))


@api_asistente.delete("/historial")
def borrar_historial():
    store = get_store()
    sid = session.get("sid", "")
    for d in store.col("conversaciones").buscar({"sid": sid}):
        store.col("conversaciones").eliminar(d["_id"])
    return jsonify({"ok": True})
