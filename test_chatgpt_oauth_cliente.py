"""Pruebas offline del adaptador experimental OAuth, sin credenciales reales."""
import io
import json
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

import chatgpt_oauth_cliente as o


def evento(t, **fields):
    return ("data: " + json.dumps({"type": t, **fields}) + "\n\n").encode()


class Respuesta(io.BytesIO):
    def __enter__(self):
        self.seek(0)
        return self
    def __exit__(self, *args):
        return False


class TestChatGPTOAuth(unittest.TestCase):
    def test_sin_sesion_no_activado(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(o, "SESSION_PATH", Path(tmp) / "no_existe"):
                state = o.estado_chatgpt_oauth()
        self.assertFalse(state["ok"])

    def test_terminacion_obligatoria(self):
        chunks = [evento("response.output_text.delta", delta='{"estado":'),
                  evento("response.output_text.delta", delta='"ok"}'),
                  evento("response.completed")]
        lines = [line for chunk in chunks for line in chunk.splitlines(keepends=True)]
        got = o._read_events(o._sse_events(lines))
        self.assertEqual(got, '{"estado":"ok"}')

    def test_incompleto_falla(self):
        with self.assertRaises(o.ChatGPTOAuthError):
            o._read_events(o._sse_events([evento("response.output_text.delta", delta="OK")]))

    def test_failed_no_expone_detalles(self):
        message = "dato-sensible-inventado"
        with self.assertRaises(o.ChatGPTOAuthError) as ctx:
            o._read_events([{"type": "response.failed", "response": {
                "error": {"code": "subscription_sharing_usage_limit_exceeded",
                          "message": message}}}])
        self.assertNotIn(message, str(ctx.exception))
        self.assertIn("subscription_sharing_usage_limit_exceeded", str(ctx.exception))

    def test_cancelacion(self):
        e = threading.Event()
        e.set()
        with self.assertRaises(o.ChatGPTOAuthError):
            o._read_events([{"type": "response.completed"}], cancelar=e)

    def test_modelos_visibles(self):
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        data = json.dumps({"models": [
            {"slug": "gpt-6.1-sol", "visibility": "list"},
            {"slug": "otro", "visibility": "hidden"},
        ]}).encode()
        with patch.object(o, "_token_acceso", return_value="falso"), patch.object(
            o.request, "urlopen", return_value=R(data)
        ):
            r = o.listar_modelos_chatgpt_oauth()
        self.assertTrue(r["ok"])
        self.assertEqual(r["models"], ["gpt-6.1-sol"])

    def test_inferencia_solo_stream_y_store_false(self):
        captured = {}
        stream = Respuesta(b"".join([
            evento("response.output_text.delta", delta='{"estado":"detenido","registros":[]}'),
            evento("response.completed")
        ]))
        def fake_urlopen(req, timeout):
            self.assertEqual(req.full_url, o.RESOURCE + "/responses")
            captured.update(json.loads(req.data))
            return stream
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "ficticio.txt"
            doc.write_text("Texto ficticio", encoding="utf-8")
            with patch.object(o, "_token_acceso", return_value="falso"), patch.object(
                o.request, "urlopen", side_effect=fake_urlopen
            ):
                ans = o.ejecutar_chatgpt_oauth(
                    prompt="Solo JSON", txt_path=doc, modelo="gpt-6.1-sol",
                )
        self.assertTrue(ans["ok"], ans.get("error"))
        self.assertIs(captured["stream"], True)
        self.assertIs(captured["store"], False)
        self.assertEqual(captured["model"], "gpt-6.1-sol")
        self.assertNotIn("max_output_tokens", captured)
        self.assertNotIn("reasoning", captured)  # La preferencia "auto" no cambia el contrato.

    def test_niveles_explicitos_se_envian_en_responses(self):
        for nivel in ("low", "medium", "high", "xhigh", "max"):
            with self.subTest(nivel=nivel), tempfile.TemporaryDirectory() as tmp:
                captured = {}
                stream = Respuesta(b"".join([
                    evento("response.output_text.delta",
                           delta='{"estado":"detenido","registros":[]}'),
                    evento("response.completed"),
                ]))
                def fake_urlopen(req, timeout):
                    captured.update(json.loads(req.data))
                    return stream
                doc = Path(tmp) / "ficticio.txt"
                doc.write_text("Solo contenido ficticio", encoding="utf-8")
                with patch.object(o, "_token_acceso", return_value="falso"), patch.object(
                    o.request, "urlopen", side_effect=fake_urlopen
                ):
                    ans = o.ejecutar_chatgpt_oauth(
                        prompt="Solo JSON", txt_path=doc, modelo="gpt-6.1-sol",
                        esfuerzo_razonamiento=nivel,
                    )
                self.assertTrue(ans["ok"], ans.get("error"))
                self.assertEqual(captured["reasoning"], {"effort": nivel})
                self.assertIs(captured["store"], False)
                self.assertIs(captured["stream"], True)
                self.assertNotIn("max_output_tokens", captured)

    def test_razonamiento_invalido_no_inicia_red(self):
        for nivel in ("none", "minimal", "ULTRA", "", None, "max\\nHeader:malicioso"):
            with self.subTest(nivel=nivel), patch.object(o.request, "urlopen") as red:
                ans = o.ejecutar_chatgpt_oauth(
                    prompt="", txt_path=Path("no-existe.txt"), modelo="gpt-6.1-sol",
                    esfuerzo_razonamiento=nivel,
                )
                self.assertFalse(ans["ok"])
                self.assertIn("razonamiento", ans["error"])
                red.assert_not_called()

    def test_la_interfaz_principal_exige_permiso_local_antes_de_extraer_pdf(self):
        # Prueba estática: no importar app_core.py (inicia Streamlit).
        src = Path(__file__).with_name("app_core.py").read_text(encoding="utf-8")
        guard = src[src.index('if modelo_preflight.startswith("chatgpt::"):'):
                    src.index('if modelo_preflight.startswith("openrouter::")')]
        self.assertIn("consultar_activacion_actas()", guard)
        self.assertIn("st.stop()", guard)
        self.assertIn("listar_modelos_chatgpt_oauth()", guard)
        self.assertNotIn("HOMCLOUD_CHATGPT_OAUTH_ACTAS", src)
        self.assertIn('not consultar_activacion_actas()["ok"]', src)

    def test_modelo_malicioso_no_inicia_red(self):
        ans = o.ejecutar_chatgpt_oauth(
            prompt="", txt_path=Path("nada.txt"), modelo="gpt-6.1-sol\nAuthorization: X",
        )
        self.assertFalse(ans["ok"])
        self.assertIn("inválido", ans["error"])

    def test_rotacion_con_bloqueo_unico(self):
        if o.fcntl is None:
            self.skipTest("Cloud Shell Linux requerido")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            session = folder / "oauth_session.json"
            session.write_text(json.dumps({
                "client_id": "oaiapp_test", "subject": "test-sub",
                "access_token": "caducado", "refresh_token": "rotar",
                "expires_at": 0, "scopes": list(o.SCOPES_NECESARIOS),
            }), encoding="utf-8")
            session.chmod(0o600)
            calls = []
            def fake_urlopen(req, timeout):
                calls.append(1)
                time.sleep(0.04)
                return Respuesta(json.dumps({
                    "access_token": "vigente", "refresh_token": "rotado",
                    "expires_in": 3600,
                }).encode())
            with patch.object(o, "CONFIG_DIR", folder), patch.object(
                o, "SESSION_PATH", session
            ), patch.object(o, "LOCK_PATH", folder / "oauth_session.lock"), patch.object(
                o.request, "urlopen", side_effect=fake_urlopen
            ):
                vals = []
                threads = [threading.Thread(target=lambda: vals.append(o._token_acceso()))
                           for _ in range(3)]
                for t in threads: t.start()
                for t in threads: t.join()
                self.assertEqual(len(calls), 1)
                self.assertEqual(vals, ["vigente"] * 3)
                self.assertEqual(json.loads(session.read_text())["refresh_token"], "rotado")


if __name__ == "__main__":
    unittest.main()
