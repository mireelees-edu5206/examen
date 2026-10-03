# -*- coding: utf-8 -*-  # Especifica codificación UTF-8 para caracteres especiales
"""Fábrica de la aplicación Flask de LogiSmart."""
import json  # Importa módulo json para manejar archivos JSON
import os  # Importa módulo os para rutas de archivos
import sys  # Importa módulo sys para manipular el path de Python

from flask import Flask, current_app  # Importa Flask y current_app para acceder a la app actual

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Agrega el directorio padre al path de Python para importar config
import config  # Importa el módulo de configuración global

from .db import Store  # Importa la clase Store (capa de persistencia) desde el módulo db


def get_store() -> Store:  # Define función que retorna una instancia de Store
    return current_app.extensions["store"]  # Retorna la instancia de Store almacenada en las extensiones de Flask


def cargar_dataset() -> list:  # Define función que carga el dataset de correos etiquetados
    if os.path.exists(config.ARCHIVO_CORREOS):  # Verifica si existe el archivo de correos etiquetados
        with open(config.ARCHIVO_CORREOS, encoding="utf-8") as f:  # Abre el archivo con codificación UTF-8
            return json.load(f)  # Carga y retorna el contenido JSON como lista
    return []  # Retorna lista vacía si el archivo no existe


def create_app(sembrar_datos: bool = True) -> Flask:  # Define fábrica de la aplicación Flask, parámetro para sembrar datos
    app = Flask(__name__)  # Crea instancia de Flask con el nombre del módulo
    app.secret_key = config.SECRET_KEY  # Establece la clave secreta para sesiones desde la configuración
    app.config["JSON_AS_ASCII"] = False  # Configura Flask para no escapar caracteres ASCII en JSON
    app.json.ensure_ascii = False  # Configura el serializador JSON de Flask para mantener caracteres Unicode

    store = Store(config.MONGO_URI, config.MONGO_DB, config.MONGO_TIMEOUT_MS,  # Crea instancia de Store con configuración MongoDB
                  config.ARCHIVO_FALLBACK)  # Pasa el archivo de fallback para modo local
    app.extensions["store"] = store  # Almacena la instancia de Store en las extensiones de Flask

    from .rutas import registrar_blueprints  # Importa la función para registrar los blueprints de rutas
    registrar_blueprints(app)  # Registra todos los blueprints (rutas) en la aplicación Flask

    if sembrar_datos:  # Si se debe sembrar datos de demostración
        try:  # Intenta ejecutar la siembra de datos
            from .seed import sembrar  # Importa la función sembrar desde el módulo seed
            sembrar(store, cargar_dataset())  # Ejecuta la siembra pasando el store y el dataset de correos
        except Exception as exc:  # Captura cualquier excepción durante la siembra
            app.logger.warning("No se pudieron sembrar los datos demo: %s", exc)  # Registra advertencia pero no detiene la app

    return app  # Retorna la aplicación Flask configurada
