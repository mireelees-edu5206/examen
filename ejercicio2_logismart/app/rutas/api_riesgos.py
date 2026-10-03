# -*- coding: utf-8 -*-
"""API de la matriz de riesgos éticos: CRUD + resumen para las gráficas."""
from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from .. import get_store
from ..db import ahora_iso
from ..esquemas import RiesgoIn, enriquecer_riesgo

api_riesgos = Blueprint("api_riesgos", __name__, url_prefix="/api/riesgos")


def _lista(store):
    docs = [enriquecer_riesgo(d) for d in store.col("riesgos_eticos").buscar()]
    docs.sort(key=lambda d: d["puntaje"], reverse=True)
    return docs


@api_riesgos.get("")
def listar():
    return jsonify(_lista(get_store()))


@api_riesgos.post("")
def crear():
    store = get_store()
    try:
        datos = RiesgoIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400
    doc = datos.model_dump()
    doc["historico"] = [{"ts": ahora_iso(), "evento": "alta de riesgo"}]
    doc["_id"] = store.col("riesgos_eticos").insertar(doc)
    return jsonify(enriquecer_riesgo(doc)), 201


@api_riesgos.route("/<doc_id>", methods=["GET", "PUT", "DELETE"])
def detalle(doc_id):
    store = get_store()
    col = store.col("riesgos_eticos")
    doc = col.buscar_por_id(doc_id)
    if not doc:
        return jsonify({"error": "no encontrado"}), 404

    if request.method == "GET":
        return jsonify(enriquecer_riesgo(doc))
    if request.method == "DELETE":
        col.eliminar(doc_id)
        return jsonify({"ok": True})

    try:
        datos = RiesgoIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400
    campos = datos.model_dump()
    cambios = [k for k, v in campos.items() if doc.get(k) != v]
    col.actualizar(doc_id, campos)
    if cambios:
        col.agregar_a_lista(doc_id, "historico",
                            {"ts": ahora_iso(), "evento": f"edición: {', '.join(cambios)}"})
    return jsonify(enriquecer_riesgo(col.buscar_por_id(doc_id)))


@api_riesgos.get("/resumen")
def resumen():
    docs = _lista(get_store())
    por_nivel = {"critico": 0, "alto": 0, "medio": 0, "bajo": 0}
    por_categoria = {}
    matriz = []  # para la gráfica de calor 5x5
    for d in docs:
        por_nivel[d["nivel"]] += 1
        por_categoria[d["categoria"]] = por_categoria.get(d["categoria"], 0) + 1
        celda = {"probabilidad": d["probabilidad"], "impacto": d["impacto"],
                 "puntaje": d["puntaje"], "descripcion": d["descripcion"][:60],
                 "modulo": d["modulo"]}
        if d.get("puntaje_residual"):
            celda.update({"prob_res": d["probabilidad_residual"],
                          "imp_res": d["impacto_residual"],
                          "puntaje_res": d["puntaje_residual"]})
        matriz.append(celda)
    return jsonify({"total": len(docs), "por_nivel": por_nivel,
                    "por_categoria": por_categoria, "matriz": matriz,
                    "riesgos": docs})
