# -*- coding: utf-8 -*-
"""Esquemas pydantic: validación de entradas de la API y del JSON del LLM."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

CATEGORIAS = [
    "materiales_peligrosos", "sobrepeso", "acceso_no_autorizado",
    "falla_hardware", "falla_software", "somnolencia_conductor", "otro",
]
PRIORIDADES = ["baja", "media", "alta", "critica"]
ESTADOS_INCIDENTE = ["nuevo", "en_atencion", "cerrado"]
CATEGORIAS_RIESGO = ["sesgo", "privacidad", "transparencia", "seguridad",
                     "responsabilidad", "otro"]


# ---------------------------------------------------------------- LLM
class Entidades(BaseModel):
    placa: Optional[str] = None
    camion_id: Optional[str] = None
    peso_reportado_kg: Optional[float] = None
    ubicacion: Optional[str] = None


class ClasificacionLLM(BaseModel):
    """Contrato JSON EXACTO que debe devolver el LLM."""
    categoria: Literal[tuple(CATEGORIAS)]
    prioridad: Literal[tuple(PRIORIDADES)]
    entidades: Entidades = Field(default_factory=Entidades)
    resumen: str = ""


# ---------------------------------------------------------------- Camiones
class CamionIn(BaseModel):
    placa: str = Field(min_length=4, max_length=15)
    camion_id: str = Field(min_length=3, max_length=15)
    empresa: str = Field(min_length=1, max_length=80)
    autorizacion: bool
    certificacion_vigente: bool
    certificacion_dias_restantes: int = Field(ge=0, le=3650, default=180)

    @field_validator("placa", "camion_id", "empresa")
    @classmethod
    def _strip(cls, v):
        return v.strip()


class CamionUpdate(BaseModel):
    placa: Optional[str] = Field(default=None, min_length=4, max_length=15)
    camion_id: Optional[str] = Field(default=None, min_length=3, max_length=15)
    empresa: Optional[str] = Field(default=None, min_length=1, max_length=80)
    autorizacion: Optional[bool] = None
    certificacion_vigente: Optional[bool] = None
    certificacion_dias_restantes: Optional[int] = Field(default=None, ge=0, le=3650)


# ---------------------------------------------------------------- Accesos
class AccesoEvaluarIn(BaseModel):
    P: bool
    Q: bool
    R: bool
    S: bool
    T: bool = False
    V: bool = False
    camion_id: Optional[str] = None
    placa: Optional[str] = None
    operador: str = "operador"
    guardar: bool = True


# ---------------------------------------------------------------- Incidentes
class ClasificarIn(BaseModel):
    asunto: str = Field(default="", max_length=300)
    cuerpo: str = Field(min_length=3, max_length=8000)
    remitente: str = Field(default="operador@logismart.local", max_length=120)
    modo: Literal["reglas", "llm", "hibrido"] = "hibrido"
    guardar: bool = True


class IncidenteUpdate(BaseModel):
    estado: Optional[Literal[tuple(ESTADOS_INCIDENTE)]] = None
    categoria: Optional[Literal[tuple(CATEGORIAS)]] = None
    prioridad: Optional[Literal[tuple(PRIORIDADES)]] = None
    nota: Optional[str] = Field(default=None, max_length=1000)


# ---------------------------------------------------------------- Riesgos
class RiesgoIn(BaseModel):
    modulo: str = Field(min_length=2, max_length=80)
    descripcion: str = Field(min_length=5, max_length=400)
    categoria: Literal[tuple(CATEGORIAS_RIESGO)]
    probabilidad: int = Field(ge=1, le=5)
    impacto: int = Field(ge=1, le=5)
    mitigacion: str = Field(default="", max_length=400)
    probabilidad_residual: Optional[int] = Field(default=None, ge=1, le=5)
    impacto_residual: Optional[int] = Field(default=None, ge=1, le=5)


def nivel_riesgo(puntaje: int) -> str:
    if puntaje >= 17:
        return "critico"
    if puntaje >= 10:
        return "alto"
    if puntaje >= 5:
        return "medio"
    return "bajo"


def enriquecer_riesgo(doc: dict) -> dict:
    """Agrega puntajes y niveles calculados a un documento de riesgo."""
    doc["puntaje"] = doc.get("probabilidad", 1) * doc.get("impacto", 1)
    doc["nivel"] = nivel_riesgo(doc["puntaje"])
    pr, ir = doc.get("probabilidad_residual"), doc.get("impacto_residual")
    doc["puntaje_residual"] = pr * ir if pr and ir else None
    doc["nivel_residual"] = nivel_riesgo(doc["puntaje_residual"]) if pr and ir else None
    return doc
