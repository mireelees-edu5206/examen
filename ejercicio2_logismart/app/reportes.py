# -*- coding: utf-8 -*-
"""Exportación de reportes a CSV y JSON (el PDF se genera en el cliente
con jsPDF para no añadir dependencias nativas)."""
import csv
import io
import json
from datetime import datetime


def a_csv(docs: list, campos: list = None) -> str:
    """Convierte documentos a CSV aplanando diccionarios anidados."""
    if not docs:
        return ""
    filas = []
    for d in docs:
        fila = {}
        _aplanar(d, "", fila)
        filas.append(fila)
    campos = campos or sorted({k for f in filas for k in f})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=campos, extrasaction="ignore")
    w.writeheader()
    w.writerows(filas)
    return buf.getvalue()


def _aplanar(d, prefijo, salida):
    for k, v in d.items():
        clave = f"{prefijo}{k}" if not prefijo else f"{prefijo}.{k}"
        if isinstance(v, dict):
            _aplanar(v, clave, salida)
        elif isinstance(v, list):
            salida[clave] = json.dumps(v, ensure_ascii=False)
        else:
            salida[clave] = v


def a_json(docs: list) -> str:
    return json.dumps(docs, ensure_ascii=False, indent=2, default=str)


def nombre_archivo(coleccion: str, ext: str) -> str:
    return f"{coleccion}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"
