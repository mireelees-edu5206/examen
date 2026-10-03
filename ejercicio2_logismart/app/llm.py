# -*- coding: utf-8 -*-  # Especifica codificación UTF-8 para caracteres especiales
"""Cliente del LLM local (Ollama).

Centraliza las llamadas para medir latencia, limitar tiempo de espera y
saber si el servicio está disponible (la GUI lo usa para los avisos).
"""
import time  # Importa módulo time para medir latencia

import ollama  # Importa librería ollama para interactuar con el LLM local


def disponible() -> bool:  # Define función para verificar si Ollama está disponible
    try:  # Intenta conectar a Ollama
        ollama.list()  # Llama a list() para verificar conexión
        return True  # Retorna True si la conexión fue exitosa
    except Exception:  # Si falla la conexión
        return False  # Retorna False indicando que no está disponible


def listar_modelos() -> list:  # Define función para listar modelos disponibles en Ollama
    try:  # Intenta obtener la lista de modelos
        return [m.get("model") for m in ollama.list().get("models", []) if m.get("model")]  # Extrae nombres de modelos
    except Exception:  # Si falla la obtención
        return []  # Retorna lista vacía


def chat(modelo: str, mensajes: list, json_mode: bool = False,  # Define función para chatear con el LLM
         timeout: int = 120) -> dict:  # Parámetros: modelo, mensajes, modo JSON, timeout en segundos
    """Llama a ollama.chat midiendo latencia.

    Devuelve {"ok": bool, "contenido": str, "latencia_ms": int, "error": str}
    """
    opciones = {"model": modelo, "messages": mensajes}  # Configura opciones básicas
    if json_mode:  # Si se solicita modo JSON
        opciones["format"] = "json"  # Agrega formato JSON a las opciones
    inicio = time.perf_counter()  # Inicia medición de tiempo
    try:  # Intenta llamar a Ollama
        respuesta = ollama.chat(**opciones)  # Ejecuta llamada a chat con las opciones
        latencia = int((time.perf_counter() - inicio) * 1000)  # Calcula latencia en milisegundos
        return {"ok": True, "contenido": respuesta["message"]["content"],  # Retorna éxito con contenido
                "latencia_ms": latencia, "error": None}  # Incluye latencia y sin error
    except Exception as exc:  # Si falla la llamada
        latencia = int((time.perf_counter() - inicio) * 1000)  # Calcula latencia incluso en error
        return {"ok": False, "contenido": "", "latencia_ms": latencia,  # Retorna error con contenido vacío
                "error": f"{type(exc).__name__}: {exc}"}  # Incluye mensaje de error
