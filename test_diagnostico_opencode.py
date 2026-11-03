"""Pruebas sin dependencias de Streamlit ni proveedor remoto."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest

from diagnostico_opencode import (
    clasificar_error,
    ejecutar_monitoreado,
    resumir_lote,
    NOMBRE_ESTADO,
)


class DiagnosticoOpenCodeTests(unittest.TestCase):
    def test_categorias_comunes(self):
        self.assertEqual(
            clasificar_error("429 Too Many Requests"),
            "HTTP 429 / cuota o rate limit",
        )
        self.assertEqual(
            clasificar_error("503 Service Unavailable"),
            "HTTP 5xx / proveedor no disponible",
        )
        self.assertEqual(
            clasificar_error("ECONNRESET"),
            "Conexión / DNS / TLS",
        )
        self.assertEqual(
            clasificar_error(""),
            "Sin mensajes en stderr",
        )

    def test_proceso_termina_y_registra_estado_sin_prompt(self):
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "outputs" / "runs" / "20261103_123456_abcdef" / "_workers" / "ejemplo" / "opencode_cwd"
            comando = [sys.executable, "-c", "print('OK')"]
            resultado = ejecutar_monitoreado(
                comando, cwd, timeout_segundos=15,
                identificador_modelo="modelo/test",
            )
            self.assertTrue(resultado["ok"], resultado)
            self.assertIn("OK", resultado["stdout"])
            estado_path = cwd.parent / NOMBRE_ESTADO
            self.assertTrue(estado_path.is_file())
            estado = json.loads(estado_path.read_text())
            self.assertEqual(estado["estado"], "completado")
            self.assertNotIn("print('OK')", estado_path.read_text())
            self.assertEqual(estado["modelo"], "modelo/test")
            filas = resumir_lote(Path(tmp), "20261103_123456_abcdef")
            self.assertEqual(len(filas), 1)
            self.assertEqual(filas[0]["Estado OpenCode"], "completado")

    def test_timeout_termina_proceso_activo(self):
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "worker" / "opencode_cwd"
            comando = [sys.executable, "-c", "import time;time.sleep(30)"]
            resultado = ejecutar_monitoreado(
                comando, cwd, timeout_segundos=1,
            )
            self.assertFalse(resultado["ok"])
            self.assertTrue(resultado["timeout"])
            self.assertEqual(
                resultado["diagnostico"]["terminacion"], "timeout_opencode"
            )
            self.assertEqual(
                resultado["diagnostico"]["estado"], "error"
            )

    def test_timeout_externo_con_evento_cancela_el_proceso(self):
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "worker" / "opencode_cwd"
            evento = threading.Event()
            evento.set()
            comando = [sys.executable, "-c", "import time;time.sleep(30)"]
            resultado = ejecutar_monitoreado(
                comando, cwd, timeout_segundos=15, cancelar=evento,
            )
            self.assertFalse(resultado["ok"])
            self.assertTrue(resultado["cancelado_por_lote"])
            self.assertEqual(
                resultado["diagnostico"]["terminacion"],
                "cancelado_por_timeout_del_lote",
            )

    def test_logs_antiguos_no_exponen_texto_privado(self):
        from diagnostico_opencode import resumir_logs_existentes
        with TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "20261103.log"
            archivo.write_text(
                "Warning: 429 too many requests for PRIVATE_PERSON_NAME\\n"
                "error: 503 Service Unavailable\\n",
                encoding="utf-8",
            )
            resultado = resumir_logs_existentes(48, carpeta=Path(tmp))
            serializado = json.dumps(resultado)
            self.assertEqual(resultado["archivos_revisados"], 1)
            self.assertIn("HTTP 429", serializado)
            self.assertIn("HTTP 5xx", serializado)
            self.assertNotIn("PRIVATE_PERSON_NAME", serializado)

    def test_no_recorre_lotes_no_validos(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                resumir_lote(Path(tmp), "../../foo")


if __name__ == "__main__":
    unittest.main()
