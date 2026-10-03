# -*- coding: utf-8 -*-
"""API de control de acceso: camiones (CRUD), evaluación de reglas y
bitácora de accesos; incluye las tablas de verdad del simulador y el
análisis de redundancia/contradicciones."""
from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from .. import get_store
from ..db import ahora_iso
from ..esquemas import AccesoEvaluarIn, CamionIn, CamionUpdate
from ..reglas import analisis_reglas, evaluar_camion, tablas_para_ui

api_accesos = Blueprint("api_accesos", __name__, url_prefix="/api")


# ------------------------------------------------------------ camiones CRUD
@api_accesos.route("/camiones", methods=["GET", "POST"])
def camiones():
    store = get_store()
    if request.method == "GET":
        filtro = {}
        if request.args.get("placa"):
            filtro["placa"] = {"$regex": request.args["placa"].strip()}
        if request.args.get("camion_id"):
            filtro["camion_id"] = request.args["camion_id"].strip().upper()
        return jsonify(store.col("camiones").buscar(filtro, orden=[("camion_id", 1)]))

    try:
        datos = CamionIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400
    doc = datos.model_dump()
    doc["placa"] = doc["placa"].upper()
    doc["camion_id"] = doc["camion_id"].upper()
    if store.col("camiones").buscar_uno({"camion_id": doc["camion_id"]}):
        return jsonify({"error": f"Ya existe un camión con id {doc['camion_id']}"}), 409
    nuevo_id = store.col("camiones").insertar(doc)
    return jsonify(store.col("camiones").buscar_por_id(nuevo_id)), 201


@api_accesos.route("/camiones/<doc_id>", methods=["GET", "PUT", "DELETE"])
def camion_detalle(doc_id):
    store = get_store()
    col = store.col("camiones")
    if request.method == "GET":
        doc = col.buscar_por_id(doc_id) or col.buscar_uno({"camion_id": doc_id.upper()})
        return jsonify(doc) if doc else (jsonify({"error": "no encontrado"}), 404)
    if request.method == "DELETE":
        ok = col.eliminar(doc_id)
        return jsonify({"ok": ok}) if ok else (jsonify({"error": "no encontrado"}), 404)
    try:
        datos = CamionUpdate.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400
    campos = {k: v for k, v in datos.model_dump().items() if v is not None}
    if "placa" in campos:
        campos["placa"] = campos["placa"].upper()
    if "camion_id" in campos:
        campos["camion_id"] = campos["camion_id"].upper()
    ok = col.actualizar(doc_id, campos)
    return jsonify(col.buscar_por_id(doc_id)) if ok else (jsonify({"error": "no encontrado"}), 404)


# -------------------------------------------------- evaluación de acceso
@api_accesos.post("/accesos/evaluar")
def evaluar_acceso():
    """Evalúa las reglas y (opcionalmente) guarda la decisión en `accesos`
    junto con la explicación paso a paso."""
    store = get_store()
    try:
        datos = AccesoEvaluarIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Datos inválidos", "detalle": exc.errors()}), 400

    res = evaluar_camion(datos.P, datos.Q, datos.R, datos.S, datos.T, datos.V)
    doc = {"camion_id": datos.camion_id, "placa": datos.placa,
           "P": datos.P, "Q": datos.Q, "R": datos.R, "S": datos.S,
           "T": datos.T, "V": datos.V,
           "A": res["A"], "E": res["E"], "H": res["H"], "W": res["W"],
           "decision": res["decision"], "semaforo": res["semaforo"],
           "explicacion": res["explicacion"],
           "operador": datos.operador, "timestamp": ahora_iso()}
    if datos.guardar:
        doc["_id"] = store.col("accesos").insertar(doc)
    return jsonify(doc)


@api_accesos.get("/accesos")
def accesos():
    store = get_store()
    filtro = {}
    if request.args.get("placa"):
        filtro["placa"] = {"$regex": request.args["placa"].strip()}
    if request.args.get("camion_id"):
        filtro["camion_id"] = request.args["camion_id"].strip().upper()
    if request.args.get("decision"):
        filtro["decision"] = request.args["decision"]
    if request.args.get("desde"):
        filtro["timestamp"] = {"$gte": request.args["desde"]}
    if request.args.get("hasta"):
        filtro.setdefault("timestamp", {})["$lte"] = request.args["hasta"] + "T23:59:59"
    limite = min(int(request.args.get("limite", 100)), 500)
    return jsonify(store.col("accesos").buscar(filtro, orden=[("timestamp", -1)], limite=limite))


# -------------------------------------------------- reglas / simulador
@api_accesos.get("/reglas/tablas")
def tablas():
    return jsonify(tablas_para_ui())


@api_accesos.post("/reglas/evaluar")
def reglas_evaluar():
    """Evalúa sin persistir: para el simulador de interruptores en vivo."""
    datos = request.get_json(force=True, silent=True) or {}
    try:
        res = evaluar_camion(bool(datos.get("P")), bool(datos.get("Q")),
                             bool(datos.get("R")), bool(datos.get("S")),
                             bool(datos.get("T")), bool(datos.get("V")))
    except TypeError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(res)


@api_accesos.get("/reglas/analisis")
def analisis():
    return jsonify(analisis_reglas())
