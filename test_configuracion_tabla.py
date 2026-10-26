"""Pruebas del orden de columnas compartido y la distribución de Plan."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import configuracion_tabla as tabla
from programas_planes_sync import EdicionDesactualizada, ErrorSincronizacion


class FakeSnapshot:
    def __init__(self, contenido=None, revision="2026-10-26"):
        self.exists = contenido is not None
        self._contenido = contenido
        self.update_time = type("Timestamp", (), {"isoformat": lambda self: revision})()

    def to_dict(self):
        return self._contenido


class FakeDocument:
    def __init__(self, contenido=None):
        self.snapshot = FakeSnapshot(contenido)
        self.guardo = None
        self.creo = None

    def get(self, timeout=12):
        return self.snapshot

    def update(self, contenido, option=None, timeout=12):
        self.guardo = contenido

    def create(self, contenido, timeout=12):
        self.creo = contenido


class FakeClient:
    def collection(self, name):
        return self

    def document(self, name):
        return self

    def write_option(self, last_update_time=None):
        return last_update_time


class VistaResumenTests(unittest.TestCase):
    def test_orden_inicial_igual_a_la_referencia(self):
        self.assertEqual(
            list(tabla.ORDEN_PREDETERMINADO[:9]),
            ["Archivo", "Prompt usado", "Programa origen", "Programa al que aspira",
             "Plan", "Nivel", "Estado", "Error", "Créditos homologados"],
        )
        self.assertEqual(tabla.ORDEN_PREDETERMINADO.index("Plan"), 4)

    def test_mover_y_restaurar_sin_perder_columnas(self):
        original = list(tabla.ORDEN_PREDETERMINADO)
        izquierda = tabla.mover_columna(original, "Plan", "izquierda")
        self.assertEqual(izquierda.index("Plan"), 3)
        derecha = tabla.mover_columna(izquierda, "Plan", "derecha")
        self.assertEqual(derecha, original)
        inicio = tabla.mover_columna(original, "Plan", "inicio")
        self.assertEqual(inicio[0], "Plan")
        self.assertEqual(len(inicio), len(set(inicio)))
        self.assertEqual(original, list(tabla.ORDEN_PREDETERMINADO))

    def test_no_ocultar_columnas_futuras(self):
        resultado = tabla.ordenar_visibles(
            ["Plan", "Archivo", "Columna nueva", "Programa origen"],
            tabla.ORDEN_PREDETERMINADO,
        )
        self.assertEqual(resultado, ["Archivo", "Programa origen", "Plan", "Columna nueva"])

    def test_orden_mal_formado_no_se_guarda(self):
        with self.assertRaises(ValueError):
            tabla.validar_orden(["Archivo", "Plan"])
        with self.assertRaises(ValueError):
            tabla.validar_orden(list(tabla.ORDEN_PREDETERMINADO[:-1]) + ["Plan"])

    def test_sin_firestore_guarda_local_y_relee(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "columns.json"
            with (
                patch.object(tabla, "ARCHIVO_LOCAL", ruta),
                patch.object(tabla, "proyecto_configurado", return_value=None),
            ):
                nuevo = tabla.mover_columna(list(tabla.ORDEN_PREDETERMINADO), "Plan", "inicio")
                tabla.guardar_orden(nuevo, None)
                leido, revision, proyecto = tabla.leer_orden()
                self.assertEqual(leido, nuevo)
                self.assertIsNone(revision)
                self.assertIsNone(proyecto)
                self.assertEqual(json.loads(ruta.read_text())["orden"], nuevo)

    def test_firestore_comparte_sin_publicar_en_lectura(self):
        doc = FakeDocument()
        cliente = FakeClient()
        with (
            patch.object(tabla, "proyecto_configurado", return_value="proyecto-comun"),
            patch.object(tabla, "_cliente_y_doc", return_value=(cliente, doc)),
        ):
            orden, revision, proyecto = tabla.leer_orden()
            self.assertEqual(orden, list(tabla.ORDEN_PREDETERMINADO))
            self.assertIsNone(doc.creo)
            tabla.guardar_orden(orden, revision)
            self.assertEqual(doc.creo["orden"], orden)

    def test_firestore_no_sobrescribe_si_revision_cambio(self):
        doc = FakeDocument({"version": 1, "orden": list(tabla.ORDEN_PREDETERMINADO)})
        with (
            patch.object(tabla, "proyecto_configurado", return_value="proyecto-comun"),
            patch.object(tabla, "_cliente_y_doc", return_value=(FakeClient(), doc)),
        ):
            with self.assertRaises(EdicionDesactualizada):
                tabla.guardar_orden(list(tabla.ORDEN_PREDETERMINADO), "revision-vieja")
            self.assertIsNone(doc.guardo)


if __name__ == "__main__":
    unittest.main()
