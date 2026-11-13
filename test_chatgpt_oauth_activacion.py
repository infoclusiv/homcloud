"""Pruebas de activación por host/identidad; nunca usa credenciales reales."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

import chatgpt_oauth_activacion as a


class ActivacionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.session = self.base / "oauth_session.json"
        self.host = self.base / "host_id.txt"
        self.permission = self.base / "settings" / "autoriza.json"
        self.session.write_text(json.dumps({
            "client_id": "oaiapp_testeo", "subject": "usuario-ficticio",
            "access_token": "falso", "refresh_token": "falso",
            "expires_at": 9999999999,
            "scopes": ["chatgpt.tokens.use.direct", "resource.invoke"]
        }), encoding="utf-8")
        self.session.chmod(0o600)
        self.host.write_text("urn:uuid:11111111-2222-3333-4444-555555555555", encoding="utf-8")
        self.host.chmod(0o600)
        self.patchers = [
            patch.object(a, "HOST_ID_PATH", self.host),
            patch.object(a, "ARCHIVO_AUTORIZACION", self.permission),
            patch.object(a, "estado_chatgpt_oauth", return_value={"ok": True}),
            patch.object(a, "_session", return_value={
                "client_id": "oaiapp_testeo", "subject": "usuario-ficticio"
            })
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_preparar_host_conserva_id_anterior(self):
        a._host_id_si_ausente()
        self.assertEqual(self.host.read_text(encoding="utf-8"),
                         "urn:uuid:11111111-2222-3333-4444-555555555555")

    def test_host_nuevo_tiene_formato_requerido_por_poc(self):
        self.host.unlink()
        a._host_id_si_ausente()
        self.assertRegex(self.host.read_text(encoding="utf-8").strip(),
                         r"^urn:uuid:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
        self.assertEqual(self.host.stat().st_mode & 0o777, 0o600)

    def test_corrige_host_legado_solo_sin_sesion_ni_autorizacion(self):
        self.host.write_text("11111111-2222-3333-4444-555555555555", encoding="utf-8")
        with patch.object(a, "SESSION_PATH", self.base / "no_oauth.json"):
            a._host_id_si_ausente()
        self.assertEqual(self.host.read_text(encoding="utf-8").strip(),
                         "urn:uuid:11111111-2222-3333-4444-555555555555")
        self.assertEqual(self.host.stat().st_mode & 0o777, 0o600)

    def test_no_reescribe_host_legado_con_sesion_existente(self):
        self.host.write_text("11111111-2222-3333-4444-555555555555", encoding="utf-8")
        with patch.object(a, "SESSION_PATH", self.session):
            with self.assertRaises(ValueError):
                a._host_id_si_ausente()
        self.assertEqual(self.host.read_text(encoding="utf-8").strip(),
                         "11111111-2222-3333-4444-555555555555")

    def test_sin_autorizacion_bloquea(self):
        self.assertFalse(a.consultar_activacion_actas()["ok"])

    def test_no_habilitar_sin_frase_exacta(self):
        with patch("builtins.input", return_value="sí"):
            self.assertFalse(a.habilitar_interactivo())
        self.assertFalse(self.permission.exists())

    def test_activa_y_revoca(self):
        with patch("builtins.input", return_value=a.FRASE_CONFIRMACION):
            self.assertTrue(a.habilitar_interactivo())
        self.assertTrue(a.consultar_activacion_actas()["ok"])
        self.assertEqual(self.permission.stat().st_mode & 0o777, 0o600)
        a.deshabilitar()
        self.assertFalse(a.consultar_activacion_actas()["ok"])

    def test_una_identidad_diferente_no_reutiliza_permiso(self):
        with patch("builtins.input", return_value=a.FRASE_CONFIRMACION):
            a.habilitar_interactivo()
        self.assertTrue(a.consultar_activacion_actas()["ok"])
        with patch.object(a, "_session", return_value={
            "client_id": "oaiapp_diferente", "subject": "otro"
        }):
            self.assertFalse(a.consultar_activacion_actas()["ok"])

    def test_host_cambiado_bloquea(self):
        with patch("builtins.input", return_value=a.FRASE_CONFIRMACION):
            a.habilitar_interactivo()
        self.host.write_text("host-ficticio-dos", encoding="utf-8")
        self.assertFalse(a.consultar_activacion_actas()["ok"])

    def test_datos_corruptos_o_permisos_amplios_bloquean(self):
        self.permission.parent.mkdir(parents=True, exist_ok=True)
        self.permission.write_text("no-json", encoding="utf-8")
        self.permission.chmod(0o600)
        self.assertFalse(a.consultar_activacion_actas()["ok"])
        self.permission.write_text(json.dumps({"enabled": True}), encoding="utf-8")
        self.assertFalse(a.consultar_activacion_actas()["ok"])
        self.permission.chmod(0o644)
        self.assertFalse(a.consultar_activacion_actas()["ok"])

    def test_symlink_no_permiso(self):
        target = self.base / "otro.json"
        target.write_text("{}", encoding="utf-8")
        self.permission.parent.mkdir(parents=True, exist_ok=True)
        self.permission.symlink_to(target)
        self.assertFalse(a.consultar_activacion_actas()["ok"])


if __name__ == "__main__":
    unittest.main()
