# -*- coding: utf-8 -*-
"""Registro de blueprints: vistas (HTML) y API REST (JSON)."""
from .vistas import vistas
from .api_nucleo import api_nucleo
from .api_accesos import api_accesos
from .api_incidentes import api_incidentes
from .api_riesgos import api_riesgos
from .api_asistente import api_asistente


def registrar_blueprints(app):
    app.register_blueprint(vistas)
    app.register_blueprint(api_nucleo)
    app.register_blueprint(api_accesos)
    app.register_blueprint(api_incidentes)
    app.register_blueprint(api_riesgos)
    app.register_blueprint(api_asistente)
