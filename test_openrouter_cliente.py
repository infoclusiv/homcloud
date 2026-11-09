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

    def test_catalogo_incluye_modelos_gratis_y_pago_compatibles_con_texto(self):
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
        self.assertEqual(modelos, ["openrouter/free", "vendor/llm:free", "vendor/paid"])
        detallados = o.extraer_modelos_openrouter(data)
        self.assertTrue(next(x for x in detallados if x["id"] == "vendor/llm:free")["gratis"])
        self.assertFalse(next(x for x in detallados if x["id"] == "vendor/paid")["gratis"])

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

    def test_modelo_pago_requiere_autorizacion_y_funciona_con_ella(self):
        with TemporaryDirectory() as tmp:
            txt = Path(tmp) / "doc.txt"
            txt.write_text("Prueba sintética", encoding="utf-8")
            reply = {"choices": [{"message": {"content": '{"estado":"detenido"}'}}]}
            with patch("openrouter_cliente.request.urlopen",
                       return_value=io.BytesIO(json.dumps(reply).encode())) as remote:
                denied = o.ejecutar_openrouter("PROMPT", txt, "vendor/paid", 8, api_key="KEY")
                self.assertFalse(denied["ok"])
                remote.assert_not_called()
                allowed = o.ejecutar_openrouter(
                    "PROMPT", txt, "vendor/paid", 8,
                    api_key="KEY", permitir_pago=True,
                )
                self.assertTrue(allowed["ok"])
                self.assertEqual(json.loads(remote.call_args.args[0].data)["model"], "vendor/paid")

    def test_clave_persistente_privada_y_recuperable(self):
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "settings" / "openrouter_api_key.txt"
            with patch.object(o, "CLAVE_LOCAL", ruta), \
                 patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
                o.guardar_api_key_openrouter("sk-or-v1-EJEMPLO123")
                self.assertEqual(o.obtener_api_key_openrouter(), "sk-or-v1-EJEMPLO123")
                self.assertEqual(ruta.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("sk-or-v1-EJEMPLO123", str(o.listar_modelos_openrouter.__name__))
                o.borrar_api_key_openrouter()
                self.assertEqual(o.obtener_api_key_openrouter(), "")

    def test_prioridad_clave_web_sobre_env_anterior(self):
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "settings" / "openrouter_api_key.txt"
            with patch.object(o, "CLAVE_LOCAL", ruta), \
                 patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-OLD"}):
                self.assertEqual(o.obtener_api_key_openrouter(), "sk-or-OLD")
                self.assertEqual(o.fuente_api_key_openrouter()["origen"], "entorno_env")
                o.guardar_api_key_openrouter("sk-or-NEW")
                self.assertEqual(o.obtener_api_key_openrouter(), "sk-or-NEW")
                fuentes = o.fuente_api_key_openrouter()
                self.assertEqual(fuentes["origen"], "archivo_privado")
                self.assertTrue(fuentes["hay_dos_fuentes"])

    def test_verificacion_clave_activa_sin_enviar_prompt(self):
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "settings" / "openrouter_api_key.txt"
            with patch.object(o, "CLAVE_LOCAL", ruta), \
                 patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
                o.guardar_api_key_openrouter("sk-or-TEST-ONLY")
                respuesta = {
                    "data": {
                        "is_free_tier": True,
                        "limit_remaining": 14.2,
                        "creator_user_id": "NO_EXPOSER_ID_USUARIO",
                        "label": "NO_EXPOSER_LABEL",
                    },
                }
                with patch("openrouter_cliente.request.urlopen", return_value=io.BytesIO(
                    json.dumps(respuesta).encode("utf-8")
                )) as llamada:
                    estado = o.verificar_api_key_openrouter()
                self.assertTrue(estado["ok"])
                self.assertEqual(estado["http_status"], 200)
                self.assertEqual(estado["origen"], "archivo_privado")
                self.assertNotIn("sk-or-TEST-ONLY", str(estado))
                self.assertNotIn("NO_EXPOSER_ID_USUARIO", str(estado))
                self.assertNotIn("NO_EXPOSER_LABEL", str(estado))
                peticion = llamada.call_args.args[0]
                self.assertEqual(peticion.get_method(), "GET")
                self.assertEqual(peticion.full_url, o.URL_CLAVE)
                self.assertIsNone(peticion.data)
                self.assertEqual(peticion.headers["Authorization"], "Bearer sk-or-TEST-ONLY")

    def test_verificacion_401_no_muestra_body_ni_key(self):
        error_401 = HTTPError(
            o.URL_CLAVE, 401, "Reason with PRIVATE PERSON",
            {}, io.BytesIO(b'{"error":{"message":"PRIVATE SECRET"}}'),
        )
        with patch("openrouter_cliente.request.urlopen", side_effect=error_401):
            estado = o.verificar_api_key_openrouter("sk-or-EXAMPLE")
        self.assertFalse(estado["ok"])
        self.assertEqual(estado["http_status"], 401)
        self.assertEqual(estado["origen"], "clave_de_sesion")
        self.assertNotIn("sk-or-EXAMPLE", str(estado))
        self.assertNotIn("PRIVATE SECRET", str(estado))
        self.assertNotIn("PRIVATE PERSON", str(estado))

    def test_no_guarda_prefijos_bearer_ni_comillas(self):
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "openrouter_api_key.txt"
            with patch.object(o, "CLAVE_LOCAL", ruta):
                for clave in ('Bearer sk-or-v1-example', '"sk-or-v1-example"'):
                    with self.subTest(clave=clave):
                        with self.assertRaises(ValueError):
                            o.guardar_api_key_openrouter(clave)
                self.assertFalse(ruta.exists())

    def test_precio_catalogo_por_millon_tokens(self):
        data = {"data": [{
            "id": "vendor/paid",
            "pricing": {"prompt": "0.00000035", "completion": "0.000001"},
        }]}
        model = next(x for x in o.extraer_modelos_openrouter(data) if x["id"] == "vendor/paid")
        self.assertAlmostEqual(model["prompt_usd_1m"], 0.35)
        self.assertAlmostEqual(model["completion_usd_1m"], 1.0)

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
