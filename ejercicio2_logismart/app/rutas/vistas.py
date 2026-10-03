# -*- coding: utf-8 -*-
"""Rutas que entregan las páginas HTML."""
from flask import Blueprint, render_template

vistas = Blueprint("vistas", __name__)


@vistas.get("/")
def dashboard():
    return render_template("dashboard.html", pagina="dashboard")


@vistas.get("/acceso")
def acceso():
    return render_template("acceso.html", pagina="acceso")


@vistas.get("/simulador")
def simulador():
    return render_template("simulador.html", pagina="simulador")


@vistas.get("/incidentes")
def incidentes():
    return render_template("incidentes.html", pagina="incidentes")


@vistas.get("/evaluacion")
def evaluacion():
    return render_template("evaluacion.html", pagina="evaluacion")


@vistas.get("/asistente")
def asistente():
    return render_template("asistente.html", pagina="asistente")


@vistas.get("/riesgos")
def riesgos():
    return render_template("riesgos.html", pagina="riesgos")


@vistas.get("/camiones")
def camiones():
    return render_template("camiones.html", pagina="camiones")


@vistas.get("/reportes")
def reportes():
    return render_template("reportes.html", pagina="reportes")


@vistas.get("/configuracion")
def configuracion():
    return render_template("configuracion.html", pagina="configuracion")
