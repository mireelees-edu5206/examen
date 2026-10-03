# -*- coding: utf-8 -*-  # Especifica codificación UTF-8 para permitir caracteres especiales (acentos, ñ)
"""Configuración global de LogiSmart.

Este archivo centraliza todas las variables de configuración de la aplicación.
Los valores pueden sobreescribirse con variables de entorno o desde la
página de Configuración de la propia aplicación (colección `configuracion`).

Secciones:
- MongoDB: URI, nombre de base de datos y timeout de conexión
- Ollama: Modelo LLM por defecto, timeout y máximo de reintentos
- Flask: Clave secreta para sesiones
- Archivos: Rutas a datos y archivos de fallback
"""
import os  # Importa módulo os para variables de entorno y rutas de archivos

# Directorio base del proyecto (donde está este archivo)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Obtiene ruta absoluta del directorio actual

# --- CONFIGURACIÓN MONGODB ------------------------------------------------
# URI de conexión a MongoDB. Por defecto usa instancia local.
# Para usar MongoDB Atlas, establecer variable de entorno:
#   set MONGO_URI=mongodb+srv://usuario:clave@cluster.../logismart
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")  # Obtiene URI de variable de entorno o usa localhost
# Nombre de la base de datos en MongoDB
MONGO_DB = os.environ.get("MONGO_DB", "logismart")  # Obtiene nombre de BD de variable de entorno o usa 'logismart'
# Timeout en milisegundos para intentar conectar a MongoDB
MONGO_TIMEOUT_MS = int(os.environ.get("MONGO_TIMEOUT_MS", "3000"))  # Convierte a entero, default 3000ms (3 segundos)

# --- CONFIGURACIÓN OLLAMA (LLM) -------------------------------------------
# Modelo de lenguaje por defecto para clasificación y asistente
MODELO_DEFAULT = os.environ.get("OLLAMA_MODEL", "llama3")  # Obtiene modelo de variable de entorno o usa 'llama3'
# Timeout en segundos para respuestas del LLM
LLM_TIMEOUT_SEG = int(os.environ.get("LLM_TIMEOUT_SEG", "120"))  # Convierte a entero, default 120 segundos
# Máximo número de reintentos cuando el LLM devuelve JSON inválido
LLM_MAX_INTENTOS = int(os.environ.get("LLM_MAX_INTENTOS", "2"))  # Convierte a entero, default 2 reintentos

# --- CONFIGURACIÓN FLASK --------------------------------------------------
# Clave secreta para sesiones y cookies (en producción usar valor seguro)
SECRET_KEY = os.environ.get("FLASK_SECRET", "logismart-dev-secret")  # Obtiene clave de variable de entorno o usa valor de desarrollo

# --- RUTAS DE ARCHIVOS -----------------------------------------------------
# Directorio donde se almacenan los datos locales
DATOS_DIR = os.path.join(BASE_DIR, "datos")  # Une ruta base con subdirectorio 'datos'
# Archivo JSON con dataset de correos etiquetados para evaluación
ARCHIVO_CORREOS = os.path.join(DATOS_DIR, "correos_etiquetados.json")  # Ruta completa al dataset de correos
# Archivo JSON de fallback cuando MongoDB no está disponible
ARCHIVO_FALLBACK = os.path.join(DATOS_DIR, "local_fallback.json")  # Ruta completa al archivo de fallback
