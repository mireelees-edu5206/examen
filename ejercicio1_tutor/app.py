#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 EJERCICIO 1 - TUTOR INTELIGENTE CON LLM (VERSIÓN WEB)
============================================================

Adaptación del script original p02primertutor_llm.py:

  1. CONFIGURACIÓN DEL SISTEMA DISTINTA:
     en lugar de un profesor de Inteligencia Artificial se
     implementa "NutriChef", un asistente experto en cocina
     saludable y nutrición básica.

  2. INTERFAZ GRÁFICA:
     aplicación web con Flask + HTML + Bootstrap que permite
     chatear con el LLM de forma intuitiva (burbujas de
     conversación, indicador de "escribiendo...", avisos de
     error amigables).

  3. RESUMEN DEL HISTORIAL:
     el botón "Resumen" pide al propio LLM una síntesis breve
     de la conversación mantenida con el usuario.

Modelo: se detecta automáticamente el primer modelo instalado
en Ollama (por defecto llama3 / llama3.2).

Uso:
    python app.py        -> http://127.0.0.1:5001
============================================================
"""

import os
import uuid

import ollama
from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "nutrichef-dev-secret")


# ------------------------------------------------------------
# 1. CONFIGURACIÓN DEL MODELO
# ------------------------------------------------------------

MODELO_DEFAULT = os.environ.get("OLLAMA_MODEL", "llama3")


def modelo_disponible() -> str:
    """Devuelve el primer modelo instalado en Ollama o el default."""
    try:
        modelos = ollama.list().get("models", [])
        if modelos:
            return modelos[0].get("model", MODELO_DEFAULT)
    except Exception:
        pass
    return MODELO_DEFAULT


# ------------------------------------------------------------
# 2. CONFIGURACIÓN DEL SISTEMA  (ejemplo DIFERENTE al original)
# ------------------------------------------------------------

MENSAJE_SISTEMA = """
Eres "NutriChef", un asistente experto en cocina saludable y
nutrición básica para personas sin experiencia culinaria.

Tu función es ayudar al usuario a cocinar mejor y comer más sano.

Debes:

1. Responder siempre en español, con tono amable y motivador.
2. Dar recetas con pasos numerados, tiempos y porciones.
3. Sugerir sustitutos económicos cuando un ingrediente sea
   difícil de conseguir.
4. Explicar brevemente el aporte nutricional de los platos
   (proteínas, fibra, vitaminas) sin usar jerga técnica.
5. Advertir sobre alergias comunes (nueces, gluten, mariscos,
   lácteos) cuando la receta los incluya.
6. Adaptar las propuestas si el usuario indica restricciones
   (vegetariano, diabético, sin horno, poco tiempo, etc.).
7. No inventar datos médicos; si la pregunta es clínica,
   recomendar consultar a un profesional de la salud.
8. Mantener respuestas concisas: máximo 3 secciones cortas.
"""


# ------------------------------------------------------------
# 3. HISTORIAL DE CONVERSACIONES (en memoria, por sesión web)
# ------------------------------------------------------------

HISTORIALES = {}
LIMITE_TURNOS = 40  # evita que el contexto crezca sin control


def historial_de(sid: str) -> list:
    """Obtiene (o crea) el historial de una sesión."""
    if sid not in HISTORIALES:
        HISTORIALES[sid] = [{"role": "system", "content": MENSAJE_SISTEMA}]
    return HISTORIALES[sid]


# ------------------------------------------------------------
# 4. RUTAS DE LA APLICACIÓN WEB
# ------------------------------------------------------------

@app.get("/")
def index():
    session.setdefault("sid", uuid.uuid4().hex)
    return render_template("index.html", modelo=modelo_disponible())


@app.get("/api/estado")
def estado():
    """Permite a la interfaz saber si Ollama responde."""
    try:
        modelos = [m.get("model") for m in ollama.list().get("models", [])]
        return jsonify({"ollama": True, "modelos": modelos,
                        "modelo": modelo_disponible()})
    except Exception as exc:
        return jsonify({"ollama": False, "error": str(exc),
                        "modelo": MODELO_DEFAULT})


@app.post("/api/chat")
def chat():
    """Recibe el mensaje del usuario y devuelve la respuesta del LLM."""
    datos = request.get_json(force=True, silent=True) or {}
    mensaje = (datos.get("mensaje") or "").strip()
    if not mensaje:
        return jsonify({"error": "Escribe un mensaje primero."}), 400
    if len(mensaje) > 4000:
        return jsonify({"error": "El mensaje es demasiado largo (máx. 4000 caracteres)."}), 400

    mensajes = historial_de(session.get("sid", "anon"))
    mensajes.append({"role": "user", "content": mensaje})

    try:
        respuesta = ollama.chat(model=modelo_disponible(), messages=mensajes)
    except Exception as exc:
        mensajes.pop()  # la pregunta no pudo procesarse: se retira del historial
        return jsonify({
            "error": "No fue posible conectar con Ollama. "
                     "Verifica que esté instalado y en ejecución (ollama serve).",
            "detalle": str(exc),
        }), 502

    contenido = respuesta["message"]["content"]
    mensajes.append({"role": "assistant", "content": contenido})

    # Recorte suave del historial conservando el mensaje de sistema
    if len(mensajes) > LIMITE_TURNOS * 2 + 1:
        del mensajes[1:3]

    return jsonify({"respuesta": contenido})


@app.post("/api/resumen")
def resumen():
    """
    PUNTO 3 DEL EJERCICIO:
    genera un resumen breve del historial para el usuario.
    """
    mensajes = historial_de(session.get("sid", "anon"))
    turnos = [m for m in mensajes if m["role"] in ("user", "assistant")]

    if not turnos:
        return jsonify({"resumen": "Todavía no hemos conversado. "
                                   "Envía tu primera pregunta y luego podré resumirla."})

    peticion = (
        "Resume en un máximo de 5 viñetas lo que el usuario ha preguntado "
        "y las recomendaciones principales que le diste en esta conversación. "
        "Habla en segunda persona ('preguntaste...', 'te sugerí...'). "
        "Si solo hubo saludos, dilo claramente."
    )
    try:
        respuesta = ollama.chat(model=modelo_disponible(),
                                messages=mensajes + [{"role": "user", "content": peticion}])
        return jsonify({"resumen": respuesta["message"]["content"]})
    except Exception as exc:
        return jsonify({"error": "Ollama no respondió al generar el resumen.",
                        "detalle": str(exc)}), 502


@app.post("/api/reiniciar")
def reiniciar():
    """Borra el historial de la sesión actual."""
    sid = session.get("sid")
    if sid in HISTORIALES:
        del HISTORIALES[sid]
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 55)
    print("  NUTRICHEF - Tutor inteligente (ejercicio 1)")
    print("  Modelo:", modelo_disponible())
    print("  Abrir:  http://127.0.0.1:5001")
    print("=" * 55)
    app.run(host="127.0.0.1", port=5001, debug=False)
