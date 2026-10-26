"""Pruebas sin credenciales de Firestore para operación compartida."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import operativa_compartida as sync
from excepciones_cloudshell import guardar_excepcion, leer_excepciones, resolver_valor
from programas_planes_sync import EdicionDesactualizada, ErrorSincronizacion


class Snapshot:
    def __init__(self, data=None):
        self.exists = data is not None
        self.data = data
        self.update_time = datetime(2026, 10, 26, tzinfo=timezone.utc)

    def to_dict(self):
        return self.data


class FakeDoc:
    def __init__(self, data=None):
        self.snapshot = Snapshot(data)
        self.created = None
        self.updated = None

    def get(self, timeout=12):
        return self.snapshot

    def create(self, payload, timeout=12):
        self.created = payload


class FakeBatch:
    def __init__(self):
        self.calls = []

    def set(self, ref, value):
        self.calls.append(("set", ref, value))

    def update(self, ref, value, option=None):
        self.calls.append(("update", ref, value))

    def commit(self):
        self.calls.append(("commit",))


class FakeClient:
    def __init__(self):
        self.batch_obj = FakeBatch()

    def batch(self):
        return self.batch_obj

    def write_option(self, last_update_time=None):
        return last_update_time


class GlobalConfigurationTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(
            sync.validar_bloque("modelo", {"modelo": " provider/model "}),
            {"modelo": "provider/model"},
        )
        self.assertEqual(sync.validar_bloque("modelo", {"modelo": ""}), {"modelo": ""})
        self.assertEqual(sync.validar_bloque("timeouts", {
            "timeout_opencode_minutos": 5, "timeout_pdf_minutos": 90,
        })["timeout_pdf_minutos"], 90)
        for valor in (None, False, 4.5, "10", 50):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                sync.validar_bloque("timeouts", {
                    "timeout_opencode_minutos": valor, "timeout_pdf_minutos": 25,
                })
        with self.assertRaises(ValueError):
            sync.validar_bloque("prompts", {"pregrado": "", "posgrado": "test"})
        with self.assertRaises(ValueError):
            sync.validar_bloque("modelo", {"modelo": "a\nb"})
        with self.assertRaises(ValueError):
            sync.validar_bloque("prompts", {"pregrado": "x" * 30001, "posgrado": "otro"})

    def test_no_auto_bootstrap_and_explicit_create(self):
        doc = FakeDoc()
        client = FakeClient()
        with patch.object(sync, "_doc", return_value=(client, doc, "project")):
            contenido, revision, proyecto = sync.leer_bloque("modelo")
            self.assertIsNone(contenido)
            self.assertIsNone(revision)
            self.assertEqual(proyecto, "project")
            self.assertIsNone(doc.created)  # leer no publica
            sync.guardar_bloque("modelo", {"modelo": "my/provider"}, None)
        self.assertEqual(doc.created["contenido"]["modelo"], "my/provider")

    def test_outdated_editor_is_blocked(self):
        doc = FakeDoc({"version": 1, "contenido": {"modelo": "current"}})
        with patch.object(sync, "_doc", return_value=(FakeClient(), doc, "project")):
            with self.assertRaises(EdicionDesactualizada):
                sync.guardar_bloque("modelo", {"modelo": "stale"}, "wrong-version")
        self.assertIsNone(doc.created)

    def test_history_batch_on_update(self):
        doc = FakeDoc({"version": 1, "contenido": {"modelo": "old"}})
        client = FakeClient()
        revision = doc.snapshot.update_time.isoformat()
        class FakeHistory:
            def document(self):
                return object()
        doc.collection = lambda name: FakeHistory()
        with patch.object(sync, "_doc", return_value=(client, doc, "project")):
            sync.guardar_bloque("modelo", {"modelo": "new"}, revision)
        self.assertEqual([x[0] for x in client.batch_obj.calls], ["set", "update", "commit"])
        self.assertEqual(client.batch_obj.calls[0][2]["contenido"]["modelo"], "old")
        self.assertEqual(client.batch_obj.calls[1][2]["contenido"]["modelo"], "new")

    def test_no_remote_writes_if_firestone_unconfigured(self):
        with patch.object(sync, "_doc", return_value=(None, None, None)):
            values, revision, project = sync.leer_bloque("modelo")
            self.assertIsNone(values)
            with self.assertRaises(ErrorSincronizacion):
                sync.guardar_bloque("modelo", {"modelo": "provider"}, None)


class ExcepcionLocalTests(unittest.TestCase):
    def test_local_flags_are_explicit_and_kept_separate(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "settings" / "optouts.json"
            flags = leer_excepciones(path)
            self.assertFalse(any(flags.values()))
            self.assertEqual(
                resolver_valor("modelo", {"modelo": "global"}, {"modelo": "local"}, flags),
                {"modelo": "global"},
            )
            guardar_excepcion("modelo", True, path)
            new_flags = leer_excepciones(path)
            self.assertTrue(new_flags["modelo"])
            self.assertEqual(
                resolver_valor("modelo", {"modelo": "global"}, {"modelo": "local"}, new_flags),
                {"modelo": "local"},
            )
            self.assertFalse(new_flags["prompts"])
            self.assertFalse(new_flags["timeouts"])

    def test_bad_override_file_never_silently_resets(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"modelo": "yes"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                leer_excepciones(path)


if __name__ == "__main__":
    unittest.main()
