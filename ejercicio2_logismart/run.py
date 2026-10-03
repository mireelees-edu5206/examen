#!/usr/bin/env python3  # Shebang para ejecutar directamente con Python 3
# -*- coding: utf-8 -*-  # Especifica codificación UTF-8 para caracteres especiales
"""Punto de entrada de LogiSmart Web.

    python run.py            -> http://127.0.0.1:5000
    python run.py --seed     -> fuerza el resembrado de datos demo
"""
import sys  # Importa módulo sys para argumentos de línea de comandos

from app import create_app  # Importa la fábrica de la aplicación Flask desde el paquete app

if __name__ == "__main__":  # Se ejecuta solo si se llama directamente (no al importar)
    app = create_app(sembrar_datos=True)  # Crea la aplicación Flask y siembra datos de demostración
    store = app.extensions["store"]  # Obtiene la instancia de Store (capa de persistencia) de las extensiones de Flask
    print("=" * 60)  # Imprime línea separadora de 60 caracteres
    print("  LogiSmart Web - centro de control inteligente")  # Imprime título de la aplicación
    print(f"  Persistencia: {store.motor.upper()}"  # Imprime el motor de persistencia (MONGODB o LOCAL)
          + ("" if store.motor == "mongodb" else "  (MongoDB no responde: modo local)"))  # Agrega aviso si está en modo local
    print("  Abrir:  http://127.0.0.1:5000")  # Imprime URL para acceder a la aplicación
    print("=" * 60)  # Imprime línea separadora de 60 caracteres
    app.run(host="127.0.0.1", port=5000, debug=False)  # Inicia el servidor Flask en localhost puerto 5000 sin modo debug
