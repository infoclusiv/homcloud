"""Pruebas locales sin red para la modalidad OpenRouter :batch."""
import unittest
from unittest.mock import patch

import diagnostico_openrouter_batch as m


class BatchDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.auth = patch(
            "diagnostico_openrouter_batch.verificar_api_key_openrouter",
            return_value={"ok": True, "http_status": 200, "mensaje": "OK"},
        )
        self.key = patch(
            "diagnostico_openrouter_batch.obtener_api_key_openrouter",
            return_value="CLAVE_PRIVADA_TEST",
        )
        self.source = patch(
            "diagnostico_openrouter_batch.fuente_api_key_openrouter",
            return_value={"origen": "archivo_privado", "archivo_privado": True, "entorno_env": False},
        )
        self.models = patch(
            "diagnostico_openrouter_batch.listar_modelos_openrouter",
            return_value={"ok": True, "models": [m.MODEL]},
        )
        for p in (self.auth, self.key, self.source, self.models):
            p.start()
            self.addCleanup(p.stop)

    def test_slug_batch_se_convierte_a_slug_base(self):
        self.assertEqual(
            m._validar_modelo("deepseek/deepseek-v4.1-flash-1017:batch"),
            "deepseek/deepseek-v4.1-flash-1017",
        )
        with self.assertRaises(ValueError):
            m._validar_modelo("deepseek/deepseek-v4.1-flash-1017")

    def test_solo_lectura_no_crea_lote(self):
        with patch("diagnostico_openrouter_batch._consulta") as consulta:
            status = m.ejecutar(
                modelo=m.MODEL, solo_lectura=True,
                permitir_pago=False, esperar=0, consultar_batch=None, timeout=5,
            )
        self.assertEqual(status, 0)
        consulta.assert_not_called()

    def test_sin_permitir_pago_no_hace_post(self):
        with patch("diagnostico_openrouter_batch._consulta") as consulta:
            status = m.ejecutar(
                modelo=m.MODEL, solo_lectura=False,
                permitir_pago=False, esperar=0, consultar_batch=None, timeout=5,
            )
        self.assertEqual(status, 2)
        consulta.assert_not_called()

    def test_envio_usa_batch_api_y_slug_sin_batch(self):
        with patch("diagnostico_openrouter_batch._consulta",
                   return_value=(202, {"id": "batch_123", "status": "validating"})) as consulta:
            status = m.ejecutar(
                modelo=m.MODEL, solo_lectura=False,
                permitir_pago=True, esperar=0, consultar_batch=None, timeout=5,
            )
        self.assertEqual(status, 3)
        self.assertEqual(consulta.call_count, 1)
        args, kw = consulta.call_args
        self.assertEqual(args[0], m.BATCHES_URL)
        self.assertEqual(args[1], "CLAVE_PRIVADA_TEST")
        payload = kw["payload"]
        self.assertEqual(payload["endpoint"], "/v1/chat/completions")
        self.assertEqual(payload["model"], "deepseek/deepseek-v4.1-flash-1017")
        self.assertEqual(payload["requests"][0]["body"]["messages"][0]["content"], "Responde solamente OK.")
        self.assertNotIn("CLAVE_PRIVADA_TEST", str(payload))

    def test_consultar_lote_existente_no_hace_post(self):
        response = {
            "status": "completed",
            "model": "deepseek/deepseek-v4.1-flash-1017",
            "results": [{
                "custom_id": m.CUSTOM_ID,
                "response": {
                    "status_code": 200,
                    "body": {"choices": [{"message": {"content": "OK"}}]},
                },
            }],
        }
        with patch("diagnostico_openrouter_batch._consulta",
                   return_value=(200, response)) as consulta:
            status = m.ejecutar(
                modelo=m.MODEL, solo_lectura=False, permitir_pago=False,
                esperar=0, consultar_batch="batch_123", timeout=5,
            )
        self.assertEqual(status, 0)
        self.assertEqual(consulta.call_count, 1)
        args, kw = consulta.call_args
        self.assertEqual(args[0], m.BATCHES_URL + "/batch_123")
        self.assertIsNone(kw.get("payload"))

    def test_rechazar_id_de_lote_no_confiable(self):
        with patch("diagnostico_openrouter_batch._consulta") as consulta:
            code = m.ejecutar(
                modelo=m.MODEL, solo_lectura=False, permitir_pago=False,
                esperar=0, consultar_batch="../private", timeout=5,
            )
        self.assertEqual(code, 2)
        consulta.assert_not_called()

    def test_con_pendiente_no_envia_nuevo_lote_en_consulta(self):
        with patch("diagnostico_openrouter_batch._consulta",
                   return_value=(200, {"status": "in_progress", "results": None})) as consulta:
            code = m.ejecutar(
                modelo=m.MODEL, solo_lectura=False, permitir_pago=False,
                esperar=0, consultar_batch="batch_abc", timeout=5,
            )
        self.assertEqual(code, 3)
        self.assertEqual(consulta.call_count, 1)


if __name__ == "__main__":
    unittest.main()
