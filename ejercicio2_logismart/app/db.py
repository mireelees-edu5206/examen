# -*- coding: utf-8 -*-  # Especifica codificación UTF-8 para caracteres especiales
"""Capa de persistencia de LogiSmart.

Intenta conectar con MongoDB (local o Atlas vía MONGO_URI). Si la
conexión falla, degrada a un almacén JSON local para que la interfaz
siga operando en modo demostración (se indica con motor='local').

Colecciones usadas:
    camiones, accesos, incidentes, riesgos_eticos, evaluaciones_llm,
    conversaciones, configuracion, meta
"""
import json  # Importa módulo json para serialización/deserialización
import os  # Importa módulo os para operaciones de archivos
import re  # Importa módulo re para expresiones regulares
import uuid  # Importa módulo uuid para generar identificadores únicos
from datetime import datetime, timezone  # Importa clases para manejo de fechas y zonas horarias

from bson import ObjectId  # Importa ObjectId de bson para manejar IDs de MongoDB
from pymongo import MongoClient  # Importa MongoClient para conectar a MongoDB
from pymongo.errors import PyMongoError  # Importa excepciones de PyMongo para manejo de errores


def ahora_iso() -> str:  # Define función que retorna marca de tiempo en formato ISO
    """Marca de tiempo UTC en ISO 8601 (comparable lexicográficamente)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # Retorna fecha/hora actual UTC en formato ISO con precisión de segundos


def a_json(doc):  # Define función para convertir documentos a tipos serializables en JSON
    """Convierte un documento a tipos serializables en JSON."""
    if doc is None:  # Si el documento es None
        return None  # Retorna None
    if isinstance(doc, list):  # Si el documento es una lista
        return [a_json(d) for d in doc]  # Retorna lista con cada elemento convertido recursivamente
    salida = {}  # Inicializa diccionario de salida
    for clave, valor in doc.items():  # Itera sobre cada clave-valor del documento
        if isinstance(valor, ObjectId):  # Si el valor es un ObjectId de MongoDB
            salida[clave] = str(valor)  # Convierte el ObjectId a string
        elif isinstance(valor, datetime):  # Si el valor es un datetime
            salida[clave] = valor.isoformat(timespec="seconds")  # Convierte el datetime a formato ISO
        elif isinstance(valor, dict):  # Si el valor es un diccionario
            salida[clave] = a_json(valor)  # Convierte recursivamente el diccionario
        elif isinstance(valor, list):  # Si el valor es una lista
            salida[clave] = [a_json(v) if isinstance(v, (dict, list)) else v for v in valor]  # Convierte recursivamente cada elemento si es dict/list
        else:  # Para cualquier otro tipo
            salida[clave] = valor  # Mantiene el valor sin cambios
    return salida  # Retorna el diccionario convertido


def _campo(doc, ruta):  # Define función auxiliar para obtener campos con notación de puntos
    """Obtiene un campo con notación de puntos: 'clasificacion.categoria'."""
    actual = doc  # Inicializa con el documento completo
    for parte in ruta.split("."):  # Separa la ruta por puntos e itera sobre cada parte
        if not isinstance(actual, dict):  # Si el valor actual no es un diccionario
            return None  # Retorna None (no se puede navegar más)
        actual = actual.get(parte)  # Obtiene el valor de la parte actual
    return actual  # Retorna el valor final


def _coincide(doc, filtro) -> bool:  # Define función para verificar si un documento coincide con un filtro
    """Matcher mínimo compatible con los operadores usados por la app."""
    for clave, esperado in (filtro or {}).items():  # Itera sobre cada clave-valor del filtro
        real = _campo(doc, clave)  # Obtiene el valor real del documento usando notación de puntos
        if isinstance(esperado, dict):  # Si el valor esperado es un diccionario (operadores de consulta)
            for op, valor in esperado.items():  # Itera sobre cada operador
                if op == "$ne" and real == valor:  # Si el operador es "no igual" y los valores son iguales
                    return False  # No coincide
                if op == "$in" and real not in valor:  # Si el operador es "en lista" y el valor no está en la lista
                    return False  # No coincide
                if op == "$gte" and (real is None or real < valor):  # Si el operador es "mayor o igual" y no cumple
                    return False  # No coincide
                if op == "$lte" and (real is None or real > valor):  # Si el operador es "menor o igual" y no cumple
                    return False  # No coincide
                if op == "$regex" and not re.search(valor, str(real or ""), re.IGNORECASE):  # Si el operador es regex y no coincide
                    return False  # No coincide
        elif real != esperado:  # Si es comparación directa y los valores no son iguales
            return False  # No coincide
    return True  # Retorna True si todas las condiciones del filtro se cumplen


def _ordenar(docs, orden):  # Define función para ordenar documentos según criterios especificados
    for campo, direccion in reversed(orden or []):  # Itera en orden inverso sobre los criterios de ordenamiento
        docs.sort(key=lambda d: str(_campo(d, campo) or ""), reverse=(direccion == -1))  # Ordena los documentos según el campo y dirección
    return docs  # Retorna los documentos ordenados


class Coleccion:  # Define clase que representa una colección de datos (interfaz uniforme para Mongo o local)
    """Interfaz uniforme sobre una colección Mongo o una lista local."""

    def __init__(self, nombre, store):  # Constructor de la clase Coleccion
        self.nombre = nombre  # Almacena el nombre de la colección
        self._store = store  # Almacena referencia al Store padre

    # -- escritura ----------------------------------------------------------
    def insertar(self, doc: dict) -> str:  # Define método para insertar un nuevo documento
        doc = dict(doc)  # Crea una copia del documento para no modificar el original
        doc.setdefault("creado_en", ahora_iso())  # Agrega timestamp de creación si no existe
        if self._store.mongo is not None:  # Si MongoDB está disponible
            res = self._store.mongo[self.nombre].insert_one(doc)  # Inserta el documento en MongoDB
            return str(res.inserted_id)  # Retorna el ID del documento insertado como string
        doc.setdefault("_id", uuid.uuid4().hex[:24])  # Genera ID único si no existe (modo local)
        self._store.local[self.nombre].append(doc)  # Agrega el documento a la lista local
        self._store.guardar_local()  # Guarda los cambios en el archivo local
        return doc["_id"]  # Retorna el ID del documento

    def actualizar(self, doc_id: str, campos: dict) -> bool:  # Define método para actualizar un documento por ID
        campos = dict(campos)  # Crea una copia de los campos a actualizar
        campos["actualizado_en"] = ahora_iso()  # Agrega timestamp de actualización
        if self._store.mongo is not None:  # Si MongoDB está disponible
            filtro = self._store.filtro_id(doc_id)  # Crea filtro para buscar por ID
            res = self._store.mongo[self.nombre].update_one(filtro, {"$set": campos})  # Actualiza el documento en MongoDB
            return res.matched_count > 0  # Retorna True si se actualizó al menos un documento
        for doc in self._store.local[self.nombre]:  # Itera sobre documentos locales
            if str(doc.get("_id")) == doc_id:  # Si encuentra el documento por ID
                doc.update(campos)  # Actualiza los campos del documento
                self._store.guardar_local()  # Guarda los cambios en el archivo local
                return True  # Retorna True indicando éxito
        return False  # Retorna False si no encontró el documento

    def eliminar(self, doc_id: str) -> bool:  # Define método para eliminar un documento por ID
        if self._store.mongo is not None:  # Si MongoDB está disponible
            res = self._store.mongo[self.nombre].delete_one(self._store.filtro_id(doc_id))  # Elimina el documento en MongoDB
            return res.deleted_count > 0  # Retorna True si se eliminó al menos un documento
        antes = len(self._store.local[self.nombre])  # Cuenta documentos antes de eliminar
        self._store.local[self.nombre] = [  # Filtra la lista excluyendo el documento a eliminar
            d for d in self._store.local[self.nombre] if str(d.get("_id")) != doc_id
        ]
        self._store.guardar_local()  # Guarda los cambios en el archivo local
        return len(self._store.local[self.nombre]) < antes  # Retorna True si la cantidad disminuyó

    def agregar_a_lista(self, doc_id: str, campo: str, item: dict) -> bool:  # Define método para agregar item a un campo lista
        """Append atómico a un campo lista (historial de cambios)."""
        if self._store.mongo is not None:  # Si MongoDB está disponible
            res = self._store.mongo[self.nombre].update_one(  # Actualiza el documento con $push (append atómico)
                self._store.filtro_id(doc_id), {"$push": {campo: item}})
            return res.matched_count > 0  # Retorna True si se actualizó al menos un documento
        for doc in self._store.local[self.nombre]:  # Itera sobre documentos locales
            if str(doc.get("_id")) == doc_id:  # Si encuentra el documento por ID
                doc.setdefault(campo, []).append(item)  # Crea la lista si no existe y agrega el item
                self._store.guardar_local()  # Guarda los cambios en el archivo local
                return True  # Retorna True indicando éxito
        return False  # Retorna False si no encontró el documento

    # -- lectura -------------------------------------------------------------
    def buscar(self, filtro=None, orden=None, limite=None) -> list:  # Define método para buscar documentos con filtros
        if self._store.mongo is not None:  # Si MongoDB está disponible
            cur = self._store.mongo[self.nombre].find(filtro or {})  # Crea cursor con el filtro especificado
            if orden:  # Si se especificó ordenamiento
                cur = cur.sort(orden)  # Aplica el ordenamiento al cursor
            if limite:  # Si se especificó límite
                cur = cur.limit(limite)  # Aplica el límite al cursor
            return [a_json(d) for d in cur]  # Retorna lista de documentos convertidos a JSON
        docs = [d for d in self._store.local[self.nombre] if _coincide(d, filtro)]  # Filtra documentos locales que coinciden
        docs = _ordenar([dict(d) for d in docs], orden)  # Ordena los documentos según criterios
        return [a_json(d) for d in (docs[:limite] if limite else docs)]  # Retorna documentos convertidos a JSON con límite aplicado

    def buscar_uno(self, filtro) -> dict:  # Define método para buscar un solo documento
        docs = self.buscar(filtro, limite=1)  # Busca documentos con límite de 1
        return docs[0] if docs else None  # Retorna el primer documento o None si no hay resultados

    def buscar_por_id(self, doc_id: str) -> dict:  # Define método para buscar un documento por su ID
        if self._store.mongo is not None:  # Si MongoDB está disponible
            return a_json(self._store.mongo[self.nombre].find_one(self._store.filtro_id(doc_id)))  # Busca y convierte a JSON
        for doc in self._store.local[self.nombre]:  # Itera sobre documentos locales
            if str(doc.get("_id")) == doc_id:  # Si encuentra el documento por ID
                return a_json(doc)  # Retorna el documento convertido a JSON
        return None  # Retorna None si no encontró el documento

    def contar(self, filtro=None) -> int:  # Define método para contar documentos que coinciden con filtro
        if self._store.mongo is not None:  # Si MongoDB está disponible
            return self._store.mongo[self.nombre].count_documents(filtro or {})  # Cuenta documentos en MongoDB
        return sum(1 for d in self._store.local[self.nombre] if _coincide(d, filtro))  # Cuenta documentos locales que coinciden

    def vaciar(self):  # Define método para eliminar todos los documentos de la colección
        if self._store.mongo is not None:  # Si MongoDB está disponible
            self._store.mongo[self.nombre].delete_many({})  # Elimina todos los documentos en MongoDB
        else:  # Si está en modo local
            self._store.local[self.nombre] = []  # Vacía la lista local
            self._store.guardar_local()  # Guarda los cambios en el archivo local


class Store:  # Define clase Store que representa la fachada de persistencia
    """Fachada de persistencia: MongoDB si responde, JSON local si no."""

    COLECCIONES = ["camiones", "accesos", "incidentes", "riesgos_eticos",  # Lista de nombres de colecciones disponibles
                   "evaluaciones_llm", "conversaciones", "configuracion", "meta"]

    def __init__(self, uri: str, nombre_db: str, timeout_ms: int = 3000,  # Constructor de la clase Store
                 archivo_fallback: str = ""):  # Parámetros: URI MongoDB, nombre BD, timeout, archivo fallback
        self.uri = uri  # Almacena la URI de conexión a MongoDB
        self.nombre_db = nombre_db  # Almacena el nombre de la base de datos
        self.timeout_ms = timeout_ms  # Almacena el timeout de conexión en milisegundos
        self.archivo_fallback = archivo_fallback  # Almacena la ruta del archivo de fallback local
        self.mongo = None  # Inicializa cliente MongoDB como None (no conectado aún)
        self.error = None  # Inicializa error como None (sin errores)
        self.local = {c: [] for c in self.COLECCIONES}  # Inicializa diccionario de datos locales con listas vacías
        self.reconectar()  # Intenta conectar a MongoDB al inicializar

    # ---------------- conexión ---------------------------------------------
    def reconectar(self) -> bool:  # Define método para reconectar a MongoDB
        try:  # Intenta conectar
            cliente = MongoClient(self.uri, serverSelectionTimeoutMS=self.timeout_ms)  # Crea cliente MongoDB con timeout
            cliente.admin.command("ping")  # Envía comando ping para verificar conexión
            self.mongo = cliente[self.nombre_db]  # Si responde, almacena la referencia a la base de datos
            self.error = None  # Limpia cualquier error previo
            return True  # Retorna True indicando conexión exitosa
        except PyMongoError as exc:  # Si falla la conexión a MongoDB
            self.mongo = None  # Establece mongo como None (no disponible)
            self.error = str(exc)  # Almacena el mensaje de error
            self._cargar_local()  # Carga datos del archivo local como fallback
            return False  # Retorna False indicando falla de conexión

    @property  # Decorador para definir una propiedad
    def motor(self) -> str:  # Define propiedad que retorna el motor de persistencia activo
        return "mongodb" if self.mongo is not None else "local"  # Retorna "mongodb" si está conectado, "local" si no

    def estado(self) -> dict:  # Define método que retorna el estado del Store
        return {"motor": self.motor, "conectado": self.mongo is not None,  # Retorna diccionario con motor y estado de conexión
                "uri": self.uri if self.mongo is not None else None,  # Incluye URI solo si está conectado
                "error": self.error}  # Incluye error si existe

    def col(self, nombre: str) -> Coleccion:  # Define método para obtener una colección por nombre
        return Coleccion(nombre, self)  # Retorna instancia de Coleccion con el nombre especificado

    def filtro_id(self, doc_id: str):  # Define método para crear filtro de búsqueda por ID
        try:  # Intenta crear filtro con ObjectId
            return {"_id": ObjectId(doc_id)}  # Retorna filtro con ObjectId de MongoDB
        except Exception:  # Si falla (ID no es ObjectId válido)
            return {"_id": doc_id}  # Retorna filtro con ID como string (para modo local)

    # ---------------- almacén local (respaldo) ------------------------------
    def _cargar_local(self):  # Define método privado para cargar datos del archivo local
        if self.archivo_fallback and os.path.exists(self.archivo_fallback):  # Si existe archivo de fallback
            try:  # Intenta cargar el archivo
                with open(self.archivo_fallback, encoding="utf-8") as f:  # Abre el archivo con codificación UTF-8
                    datos = json.load(f)  # Carga el contenido JSON
                for c in self.COLECCIONES:  # Itera sobre cada colección
                    self.local[c] = datos.get(c, [])  # Carga los datos de cada colección o lista vacía si no existe
            except (json.JSONDecodeError, OSError):  # Si hay error al leer el archivo
                pass  # Ignora el error y continúa con listas vacías

    def guardar_local(self):  # Define método para guardar datos en el archivo local
        if not self.archivo_fallback:  # Si no hay archivo de fallback configurado
            return  # Retorna sin hacer nada
        os.makedirs(os.path.dirname(self.archivo_fallback), exist_ok=True)  # Crea directorio si no existe
        tmp = self.archivo_fallback + ".tmp"  # Crea nombre de archivo temporal
        with open(tmp, "w", encoding="utf-8") as f:  # Abre archivo temporal para escritura
            json.dump(self.local, f, ensure_ascii=False, default=str)  # Escribe datos JSON con UTF-8 y conversión de tipos
        os.replace(tmp, self.archivo_fallback)  # Reemplaza archivo original con temporal (operación atómica)

    # ---------------- configuración persistente ----------------------------
    def obtener_config(self) -> dict:  # Define método para obtener configuración persistente
        doc = self.col("configuracion").buscar_uno({"_tipo": "app"})  # Busca documento de configuración de la app
        if not doc:  # Si no existe configuración
            doc = {"_tipo": "app", "modelo": None, "umbral_confianza": 0.5,  # Crea configuración por defecto
                   "simulacion_correo": True, "operador": "operador"}
            self.col("configuracion").insertar(doc)  # Inserta la configuración por defecto
        return doc  # Retorna el documento de configuración

    def guardar_config(self, campos: dict):  # Define método para guardar configuración
        cfg = self.obtener_config()  # Obtiene la configuración actual
        self.col("configuracion").actualizar(cfg["_id"], campos)  # Actualiza la configuración con los campos especificados

    # ---------------- agregación: incidentes por categoría y semana --------
    def incidentes_por_categoria_semana(self) -> list:  # Define método para agregar incidentes por categoría y semana
        """Agregación real en MongoDB ($group); equivalente en Python si
        se está en modo local. Devuelve [{categoria, semana, total}]."""
        if self.mongo is not None:  # Si MongoDB está disponible
            pipeline = [  # Define pipeline de agregación de MongoDB
                {"$group": {  # Primera etapa: agrupar por categoría, semana y año
                    "_id": {  # Define los campos de agrupación
                        "categoria": "$clasificacion.categoria",  # Agrupa por categoría de clasificación
                        "semana": {"$isoWeek": {"$dateFromString": {"dateString": "$timestamp"}}},  # Extrae semana ISO del timestamp
                        "anio": {"$isoWeekYear": {"$dateFromString": {"dateString": "$timestamp"}}},  # Extrae año ISO del timestamp
                    },
                    "total": {"$sum": 1},  # Cuenta el total de incidentes por grupo
                }},
                {"$sort": {"_id.anio": 1, "_id.semana": 1}},  # Ordena por año y semana ascendente
            ]
            return [{"categoria": d["_id"]["categoria"] or "otro",  # Retorna lista con resultados formateados
                     "semana": d["_id"]["semana"], "anio": d["_id"]["anio"],  # Incluye semana y año
                     "total": d["total"]}  # Incluye total de incidentes
                    for d in self.mongo["incidentes"].aggregate(pipeline)]  # Ejecuta la agregación en MongoDB
        grupos = {}  # Inicializa diccionario para agrupar (modo local)
        for d in self.local["incidentes"]:  # Itera sobre incidentes locales
            try:  # Intenta parsear la fecha
                fecha = datetime.fromisoformat(str(d.get("timestamp", ""))[:26])  # Convierte timestamp a datetime
                anio, semana, _ = fecha.isocalendar()  # Obtiene año y semana ISO
            except ValueError:  # Si falla el parseo
                anio = semana = 0  # Usa valores por defecto
            clave = (d.get("clasificacion", {}).get("categoria", "otro"), anio, semana)  # Crea clave de agrupación
            grupos[clave] = grupos.get(clave, 0) + 1  # Incrementa contador para esta clave
        return [{"categoria": c, "anio": a, "semana": s, "total": t}  # Retorna lista con resultados formateados
                for (c, a, s), t in sorted(grupos.items(), key=lambda x: (x[0][1], x[0][2]))]  # Ordena por año y semana
