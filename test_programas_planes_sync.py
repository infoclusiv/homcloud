import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from programas_planes_sync import (
    EdicionDesactualizada,
    ErrorSincronizacion,
    _leer_origen_seguro,
    guardar_configuracion,
    inicializar_desde_infoclusiv,
    leer_configuracion,
)
from programas_planes import PROGRAMAS_PLANES_DEFAULT, guardar_programas_planes


class FakeSnapshot:
    exists = True
    update_time = None

    def __init__(self, filas):
        from datetime import datetime, timezone
        self.update_time = datetime(2026, 10, 20, tzinfo=timezone.utc)
        self.filas = filas

    def to_dict(self):
        return {"version": 4, "programas": self.filas}


class FakeDocument:
    def __init__(self, filas):
        self.snapshot = FakeSnapshot(filas)
        self.created = None

    def get(self, timeout=12):
        return self.snapshot

    def create(self, payload):
        self.created = payload


class TestSync(unittest.TestCase):
    def test_no_bootstrap_default_if_local_file_missing(self):
        with TemporaryDirectory() as p:
            with self.assertRaises(ErrorSincronizacion):
                _leer_origen_seguro(Path(p) / "missing.json")

    def test_bootstrap_exact_primary_file(self):
        with TemporaryDirectory() as p:
            path = Path(p) / "programas_planes.json"
            filas = PROGRAMAS_PLANES_DEFAULT[:2]
            guardar_programas_planes(filas, path)
            doc = FakeDocument([])
            with patch("programas_planes_sync._conectar", return_value=(None, doc)):
                result = inicializar_desde_infoclusiv(path)
            self.assertEqual(len(result), 2)
            self.assertEqual(doc.created["origen_inicial"], "infoclusiv")
            self.assertEqual(doc.created["programas"], result)
            self.assertEqual(len(list((path.parent / "backups").glob("*.json"))), 1)

    def test_local_fallback_when_not_configured(self):
        with TemporaryDirectory() as p, patch(
            "programas_planes_sync.proyecto_configurado", return_value=None
        ):
            path = Path(p) / "programas_planes.json"
            guardar_programas_planes(PROGRAMAS_PLANES_DEFAULT[:2], path)
            filas, revision, proyecto = leer_configuracion(path)
            self.assertEqual(len(filas), 2)
            self.assertIsNone(revision)
            self.assertIsNone(proyecto)

    def test_remote_read(self):
        doc = FakeDocument(PROGRAMAS_PLANES_DEFAULT)
        with patch("programas_planes_sync.proyecto_configurado", return_value="my-sample-project"), patch(
            "programas_planes_sync._conectar", return_value=(None, doc)
        ):
            filas, revision, proyecto = leer_configuracion()
        self.assertEqual(len(filas), 35)
        self.assertIn("2026-10-20", revision)
        self.assertEqual(proyecto, "my-sample-project")

    def test_outdated_editor_never_saves(self):
        doc = FakeDocument(PROGRAMAS_PLANES_DEFAULT)
        with TemporaryDirectory() as p, patch(
            "programas_planes_sync.proyecto_configurado", return_value="my-sample-project"
        ), patch("programas_planes_sync._conectar", return_value=(None, doc)):
            path = Path(p) / "programas_planes.json"
            with self.assertRaises(EdicionDesactualizada):
                guardar_configuracion(PROGRAMAS_PLANES_DEFAULT, path, "previous-revision")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
