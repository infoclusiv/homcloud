"""Pruebas sin red ni secretos para el diagnóstico OpenRouter 404."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import diagnostico_openrouter_terminal as d


class DiagnosticoOpenRouterTerminalTests(unittest.TestCase):
    def test_no_imprime_secreto_en_error(self):
        mensaje = {
            "error": {
                "code": 404,
                "message": "No endpoints for model. Bearer abcsecret sk-or-v1-secret123 user@demo.com",
            }
        }
        safe = d._resumir_error(mensaje, "abcsecret")
        out = json.dumps(safe)
        self.assertIn("No endpoints", out)
        self.assertNotIn("abcsecret", out)
        self.assertNotIn("sk-or-v1-secret123", out)
        self.assertNotIn("user@demo.com", out)

    def test_http_404_conserva_error_openrouter_sin_cuerpo_crudo(self):
        fallo = HTTPError(
            d.URL_CHAT, 404, "PRIVATE SERVER REASON", {},
            io.BytesIO(json.dumps({
                "error": {"message": "No endpoints available for chosen model", "code": 404},
                "private_debug": "PRIVATE_INTERNAL_FIELD",
            }).encode("utf-8")),
        )
        with patch("diagnostico_openrouter_terminal.request.urlopen", side_effect=fallo):
            status, body = d._consulta(d.URL_CHAT, "SECRET-KEY", payload={
                "model": "vendor/test:free", "messages": [{"role": "user", "content": "OK"}]
            })
        self.assertEqual(status, 404)
        summary = d._resumir_error(body, "SECRET-KEY")
        self.assertEqual(summary["codigo"], 404)
        self.assertIn("No endpoints", summary["mensaje"])
        self.assertNotIn("PRIVATE_INTERNAL_FIELD", str(summary))

    def test_falla_sin_key_y_no_envia_chat(self):
        with patch("diagnostico_openrouter_terminal.verificar_api_key_openrouter",
                   return_value={"ok": False, "http_status": 401, "mensaje": "No reconocida"}), \
             patch("diagnostico_openrouter_terminal.obtener_api_key_openrouter", return_value="INVALID"), \
             patch("diagnostico_openrouter_terminal.fuente_api_key_openrouter",
                   return_value={"origen": "archivo_privado", "archivo_privado": True, "entorno_env": False}), \
             patch("diagnostico_openrouter_terminal._consulta") as consulta:
            res, code = d.diagnosticar(
                "openrouter/free", solo_lectura=False, permitir_pago=False, timeout=10,
            )
        self.assertEqual(code, 2)
        self.assertEqual(res["consulta_key"]["http"], 401)
        consulta.assert_not_called()

    def test_modelo_pago_requiere_consentimiento(self):
        with patch("diagnostico_openrouter_terminal.verificar_api_key_openrouter",
                   return_value={"ok": True, "http_status": 200, "mensaje": "OK"}), \
             patch("diagnostico_openrouter_terminal.obtener_api_key_openrouter", return_value="KEY"), \
             patch("diagnostico_openrouter_terminal.fuente_api_key_openrouter",
                   return_value={"origen": "archivo_privado", "archivo_privado": True, "entorno_env": False}), \
             patch("diagnostico_openrouter_terminal.listar_modelos_openrouter",
                   return_value={"ok": True, "models": ["vendor/paid"]}), \
             patch("diagnostico_openrouter_terminal._consulta",
                   return_value=(200, {"data": {"endpoints": [{"name": "Test"}]}})) as consulta:
            result, code = d.diagnosticar(
                "vendor/paid", solo_lectura=False, permitir_pago=False, timeout=10,
            )
        self.assertEqual(code, 2)
        self.assertEqual(result["inferencia_http"], "no ejecutada")
        self.assertEqual(consulta.call_count, 1)
        self.assertEqual(consulta.call_args.kwargs.get("payload"), None)

    def test_404_revela_modelo_sin_endpoints(self):
        with patch("diagnostico_openrouter_terminal.verificar_api_key_openrouter",
                   return_value={"ok": True, "http_status": 200, "mensaje": "OK"}), \
             patch("diagnostico_openrouter_terminal.obtener_api_key_openrouter", return_value="SECRET"), \
             patch("diagnostico_openrouter_terminal.fuente_api_key_openrouter",
                   return_value={"origen": "archivo_privado", "archivo_privado": True, "entorno_env": False}), \
             patch("diagnostico_openrouter_terminal.listar_modelos_openrouter",
                   return_value={"ok": True, "models": ["vendor/test:free"]}), \
             patch("diagnostico_openrouter_terminal._consulta", side_effect=[
                 (200, {"data": {"endpoints": []}}),
                 (404, {"error": {"message": "No endpoints available", "code": 404}}),
             ]) as consulta:
            result, code = d.diagnosticar(
                "vendor/test:free", solo_lectura=False, permitir_pago=False, timeout=10,
            )
        self.assertEqual(code, 1)
        self.assertEqual(result["cantidad_endpoints"], 0)
        self.assertEqual(result["inferencia_http"], 404)
        self.assertIn("sin proveedor", result["orientacion"])
        self.assertIn("No endpoints", result["error_openrouter"]["mensaje"])
        self.assertEqual(consulta.call_count, 2)
        self.assertEqual(consulta.call_args.kwargs["payload"]["messages"][0]["content"],
                         "Responde solo OK.")
        self.assertNotIn("SECRET", json.dumps(result))

    def test_gratuito_200_con_solo_una_inferencia_sintetica(self):
        with patch("diagnostico_openrouter_terminal.verificar_api_key_openrouter",
                   return_value={"ok": True, "http_status": 200, "mensaje": "OK"}), \
             patch("diagnostico_openrouter_terminal.obtener_api_key_openrouter", return_value="KEY"), \
             patch("diagnostico_openrouter_terminal.fuente_api_key_openrouter",
                   return_value={"origen": "archivo_privado", "archivo_privado": True, "entorno_env": False}), \
             patch("diagnostico_openrouter_terminal.listar_modelos_openrouter",
                   return_value={"ok": True, "models": ["openrouter/free"]}), \
             patch("diagnostico_openrouter_terminal._consulta",
                   return_value=(200, {"choices": [{"message": {"content": "OK"}}],
                                       "model": "vendor/random:free", "usage": {"total_tokens": 17}})) as consulta:
            result, code = d.diagnosticar(
                "openrouter/free", solo_lectura=False, permitir_pago=False, timeout=10,
            )
        self.assertEqual(code, 0)
        self.assertEqual(consulta.call_count, 1)
        self.assertEqual(result["inferencia_http"], 200)
        self.assertEqual(result["respuesta"], "OK")
        self.assertEqual(result["tokens"]["total_tokens"], 17)


if __name__ == "__main__":
    unittest.main()
