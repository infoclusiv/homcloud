"""Pruebas offline del motor OpenRouter: sin solicitudes reales ni claves."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import openrouter_cliente as o


class OpenRouterTests(unittest.TestCase):
    def test_solo_modelos_gratuitos(self):
        self.assertTrue(o.modelo_gratuito("openrouter/free"))
        self.assertTrue(o.modelo_gratuito("qwen/qwen3:free"))
        for model in ("", "openai/gpt-4o", "openrouter/auto", "qwen/qwen3:free\n", None):
            self.assertFalse(o.modelo_gratuito(model))

    def test_catalogo_filtra_a_modelos_de_chat_gratuitos(self):
        data = {"data": [
            {"id": "vendor/llm:free", "architecture": {
                "input_modalities": ["text"], "output_modalities": ["text"],
            }},
            {"id": "vendor/imagenes:free", "architecture": {
                "input_modalities": ["image"], "output_modalities": ["image"],
            }},
            {"id": "vendor/paid", "architecture": {
                "input_modalities": ["text"], "output_modalities": ["text"],
            }},
        ]}
        modelos = o.validar_lista_modelos(data)
        self.assertEqual(modelos, ["openrouter/free", "vendor/llm:free"])

    def test_catalogo_no_manda_api_key(self):
        payload = json.dumps({"data": [{"id": "vendor/free:free"}]}).encode("utf-8")
        with patch("openrouter_cliente.request.urlopen", return_value=io.BytesIO(payload)) as mock:
            data = o.listar_modelos_openrouter()
            self.assertTrue(data["ok"])
            req = mock.call_args.args[0]
            self.assertEqual(req.get_method(), "GET")
            self.assertNotIn("Authorization", req.headers)

    def test_peticion_envia_prompt_y_txt_ademas_de_clave_privada(self):
        with TemporaryDirectory() as tmp:
            txt = Path(tmp) / "documento.txt"
            txt.write_text("CONTENIDO PRIVADO DEL DOCUMENTO", encoding="utf-8")
            response = {
                "choices": [{"message": {"content": '{"estado":"detenido","motivo_detencion":"test"}'}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52},
            }
            with patch("openrouter_cliente.request.urlopen",
                       return_value=io.BytesIO(json.dumps(response).encode())) as mock:
                resultado = o.ejecutar_openrouter(
                    "CONTRATO JSON", txt, "vendor/model:free", 10,
                    api_key="SECRETO_APITEST_NO_PUBLICAR",
                )
            self.assertTrue(resultado["ok"])
            self.assertIn('"estado":"detenido"', resultado["stdout"])
            self.assertEqual(resultado["usage"]["total_tokens"], 52)
            req = mock.call_args.args[0]
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(req.headers["Authorization"], "Bearer SECRETO_APITEST_NO_PUBLICAR")
            cuerpo = json.loads(req.data.decode("utf-8"))
            self.assertEqual(cuerpo["model"], "vendor/model:free")
            self.assertIn("CONTRATO JSON", cuerpo["messages"][0]["content"])
            self.assertIn("CONTENIDO PRIVADO", cuerpo["messages"][1]["content"])
            self.assertNotIn("SECRETO_APITEST_NO_PUBLICAR", json.dumps(resultado))
            self.assertNotIn("CONTENIDO PRIVADO", json.dumps(resultado))

    def test_http_429_no_registra_error_crudo(self):
        with TemporaryDirectory() as tmp:
            txt = Path(tmp) / "doc.txt"
            txt.write_text("información de un estudiante", encoding="utf-8")
            fallo = HTTPError(
                o.URL_CHAT, 429, "cuota superada para estudiante",
                {}, io.BytesIO(b"private bearer secret"),
            )
            with patch("openrouter_cliente.request.urlopen", side_effect=fallo):
                resultado = o.ejecutar_openrouter(
                    "PROMPT", txt, "vendor/model:free", 5, api_key="CLAVE_PRIVADA",
                )
            self.assertFalse(resultado["ok"])
            self.assertEqual(resultado["returncode"], 429)
            self.assertIn("429", resultado["error"])
            self.assertNotIn("estudiante", str(resultado))
            self.assertNotIn("CLAVE_PRIVADA", str(resultado))
            self.assertNotIn("secret", str(resultado))

    def test_no_permite_modelo_pago_ni_con_llave(self):
        with TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "doc.txt"
            archivo.write_text("PRIVATE", encoding="utf-8")
            with patch("openrouter_cliente.request.urlopen") as mock:
                resultado = o.ejecutar_openrouter(
                    "REGLAS", archivo, "openai/gpt-4o", 5, api_key="KEY",
                )
            self.assertFalse(resultado["ok"])
            mock.assert_not_called()

    def test_cancelar_antes_de_enviar_no_consume_cuota(self):
        with TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "doc.txt"
            archivo.write_text("PRIVADO", encoding="utf-8")
            evento = threading.Event()
            evento.set()
            with patch("openrouter_cliente.request.urlopen") as mock:
                resultado = o.ejecutar_openrouter(
                    "REGLAS", archivo, "openrouter/free", 5, cancelar=evento,
                    api_key="KEY",
                )
            self.assertFalse(resultado["ok"])
            self.assertTrue(resultado["timeout"])
            mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
