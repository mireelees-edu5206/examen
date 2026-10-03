# -*- coding: utf-8 -*-
"""Pruebas unitarias de LogiSmart Web.

    python -m unittest discover -s tests -v   (desde ejercicio2_logismart)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import clasificador, reglas
from app.db import _coincide
from app.esquemas import ClasificacionLLM, RiesgoIn, nivel_riesgo


class TestReglas(unittest.TestCase):
    """Motor de reglas: reglas originales + nuevas + decisión final."""

    def test_acceso_estandar(self):
        r = reglas.evaluar_camion(True, False, False, True)
        self.assertTrue(r["A"]) and self.assertFalse(r["E"])
        self.assertEqual(r["decision"], "acceso_estandar")
        self.assertEqual(r["semaforo"], "verde")

    def test_inspeccion_por_peso_y_por_peligrosos(self):
        self.assertEqual(reglas.evaluar_camion(True, True, False, True)["decision"], "inspeccion_especial")
        self.assertEqual(reglas.evaluar_camion(True, False, True, True)["decision"], "inspeccion_especial")

    def test_sin_autorizacion_denegado(self):
        import itertools
        for q, r_, s, t, v in itertools.product([True, False], repeat=5):
            self.assertEqual(reglas.evaluar_camion(False, q, r_, s, t, v)["decision"], "denegado")

    def test_regla_nueva_horario(self):
        """H = R∧T retiene aunque A y E valgan."""
        r = reglas.evaluar_camion(True, False, True, True, T=True)
        self.assertTrue(r["H"])
        self.assertEqual(r["decision"], "retenido_horario")
        self.assertEqual(r["semaforo"], "rojo")
        # sin T no hay retención
        r2 = reglas.evaluar_camion(True, False, True, True, T=False)
        self.assertFalse(r2["H"])
        self.assertEqual(r2["decision"], "inspeccion_especial")

    def test_regla_nueva_certificacion_por_vencer(self):
        """W = S∧V: acceso estándar permitido pero con alerta (semáforo amarillo)."""
        r = reglas.evaluar_camion(True, False, False, True, V=True)
        self.assertTrue(r["W"])
        self.assertEqual(r["decision"], "acceso_estandar")
        self.assertEqual(r["semaforo"], "amarillo")

    def test_explicacion_incluye_premisas(self):
        r = reglas.evaluar_camion(True, True, False, True)
        self.assertTrue(any("Q=V" in p for p in r["explicacion"]))
        self.assertGreaterEqual(len(r["explicacion"]), 10)

    def test_tabla_original_16_filas(self):
        self.assertEqual(len(reglas.tabla_verdad()), 16)

    def test_tablas_nuevas_reglas(self):
        t = reglas.tablas_para_ui()
        self.assertEqual(len(t["H"]), 4)
        self.assertEqual(len(t["W"]), 4)

    def test_analisis_sin_contradiccion(self):
        a = reglas.analisis_reglas()
        self.assertFalse(a["hay_contradiccion_logica"])
        self.assertEqual(a["redundantes"], [])
        # A y E valen a la vez cuando P∧S∧¬Q∧R -> conflicto conocido y resuelto
        self.assertGreater(a["conflictos"][2]["casos"], 0)


class TestClasificadorReglas(unittest.TestCase):
    CORREO = dict(asunto="URGENTE: derrame en andén 3",
                  cuerpo="El camión CAM-102 con placas ABC-123-D presenta fuga de "
                         "químico inflamable. La báscula marcó 48.5 toneladas.")

    def test_categoria_y_prioridad(self):
        c = clasificador.clasificar_por_reglas(**self.CORREO)
        self.assertEqual(c["categoria"], "materiales_peligrosos")
        self.assertEqual(c["prioridad"], "critica")

    def test_extraccion_entidades(self):
        e = clasificador.extraer_datos(**self.CORREO)
        self.assertEqual(e["placa"], "ABC-123-D")
        self.assertEqual(e["camion_id"], "CAM-102")
        self.assertEqual(e["peso_reportado_kg"], 48500.0)
        self.assertEqual(e["ubicacion"], "andén 3")

    def test_urgencia_escala_prioridad(self):
        normal = clasificador.clasificar_por_reglas("Pantalla lenta", "El sistema carga lento")
        urgente = clasificador.clasificar_por_reglas("Pantalla lenta urgente", "El sistema carga lento")
        self.assertEqual(normal["prioridad"], "baja")
        self.assertEqual(urgente["prioridad"], "media")

    def test_modo_reglas_no_requiere_llm(self):
        r = clasificador.clasificar(**self.CORREO, modo="reglas")
        self.assertEqual(r["fuente"], "reglas")
        self.assertFalse(r["requiere_revision_humana"])

    def test_hibrido_cae_a_reglas_sin_llm(self):
        """Sin Ollama el híbrido debe seguir funcionando (plan de respaldo)."""
        r = clasificador.clasificar("Consulta", "Hola, tengo una duda general.",
                                    modo="hibrido", modelo="modelo-inexistente")
        if r.get("error_llm"):  # LLM no disponible en este entorno
            self.assertIn("reglas", r["fuente"])
        self.assertIn(r["categoria"], clasificador.PRIORIDAD_BASE)

    def test_dataset_minimo_30(self):
        import json
        ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "datos", "correos_etiquetados.json")
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        self.assertGreaterEqual(len(datos), 30)
        for item in datos:
            self.assertIn(item["categoria"], clasificador.PRIORIDAD_BASE)
            self.assertIn(item["prioridad"], clasificador.ORDEN_PRIORIDAD)


class TestEsquemas(unittest.TestCase):
    def test_json_llm_valido(self):
        c = ClasificacionLLM.model_validate({
            "categoria": "sobrepeso", "prioridad": "media",
            "entidades": {"placa": "ABC-123-D", "camion_id": None,
                          "peso_reportado_kg": 52000, "ubicacion": None},
            "resumen": "Camión con exceso de peso"})
        self.assertEqual(c.entidades.placa, "ABC-123-D")

    def test_json_llm_invalido_rechazado(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ClasificacionLLM.model_validate({"categoria": "inventada", "prioridad": "media"})

    def test_niveles_riesgo(self):
        self.assertEqual(nivel_riesgo(20), "critico")
        self.assertEqual(nivel_riesgo(12), "alto")
        self.assertEqual(nivel_riesgo(6), "medio")
        self.assertEqual(nivel_riesgo(4), "bajo")

    def test_riesgo_valida_escalas(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            RiesgoIn(modulo="x", descripcion="desc", categoria="sesgo",
                     probabilidad=6, impacto=1)


class TestMatcherLocal(unittest.TestCase):
    def test_operadores(self):
        doc = {"estado": "nuevo", "clasificacion": {"categoria": "sobrepeso"}, "n": 5}
        self.assertTrue(_coincide(doc, {"estado": "nuevo"}))
        self.assertTrue(_coincide(doc, {"clasificacion.categoria": "sobrepeso"}))
        self.assertTrue(_coincide(doc, {"estado": {"$in": ["nuevo", "en_atencion"]}}))
        self.assertTrue(_coincide(doc, {"n": {"$gte": 5, "$lte": 10}}))
        self.assertFalse(_coincide(doc, {"estado": {"$ne": "nuevo"}}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
