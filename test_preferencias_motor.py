"""Pruebas offline: modelo DeepSeek predeterminado y autorización persistente."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import preferencias_motor as p


class PreferenciasMotorTests(unittest.TestCase):
    def test_default_deepseek_sin_archivo(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "preferido.txt"
            self.assertEqual(
                p.cargar_motor_preferido(ruta),
                "openrouter::deepseek/deepseek-v4-flash-0731",
            )
            self.assertTrue(p.autorizar_pago_automatico(p.cargar_motor_preferido(ruta)))
            self.assertFalse(ruta.exists())  # nunca sobrescribir modelo_opencode legado

    def test_modelo_elegido_persiste_y_se_recupera(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "settings" / "preferido.txt"
            p.guardar_motor_preferido("openrouter::google/gemini-2.5-pro", ruta)
            self.assertEqual(
                p.cargar_motor_preferido(ruta), "openrouter::google/gemini-2.5-pro"
            )
            self.assertEqual(ruta.stat().st_mode & 0o777, 0o600)
            p.guardar_motor_preferido(
                "openrouter::deepseek/deepseek-v4-flash-0731", ruta
            )
            self.assertEqual(p.cargar_motor_preferido(ruta),
                             p.MODELO_DEEPSEEK_PREDETERMINADO)

    def test_opencode_y_modelo_default_opencode_no_se_pierden(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "preferido.txt"
            p.guardar_motor_preferido("opencode/glm-5.3-flash-free", ruta)
            self.assertEqual(p.cargar_motor_preferido(ruta), "opencode/glm-5.3-flash-free")
            p.guardar_motor_preferido("", ruta)
            self.assertEqual(p.cargar_motor_preferido(ruta), "")

    def test_fichero_corrupto_no_impide_iniciar(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "preferido.txt"
            ruta.write_text("bad model\nwith newline", encoding="utf-8")
            self.assertEqual(p.cargar_motor_preferido(ruta),
                             p.MODELO_DEEPSEEK_PREDETERMINADO)

    def test_no_guardar_modelo_invalido(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "preferido.txt"
            for modelo in ("provider model", "a\nb", "a" * 205, None):
                with self.subTest(modelo=modelo):
                    with self.assertRaises(ValueError):
                        p.guardar_motor_preferido(modelo, ruta)
            self.assertFalse(ruta.exists())

    def test_razonamiento_oauth_persiste_entre_inicios(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "settings" / "razonamiento.txt"
            self.assertEqual(p.cargar_razonamiento_chatgpt_oauth(ruta), "auto")
            self.assertFalse(ruta.exists())
            p.guardar_razonamiento_chatgpt_oauth("xhigh", ruta)
            self.assertEqual(p.cargar_razonamiento_chatgpt_oauth(ruta), "xhigh")
            self.assertEqual(ruta.stat().st_mode & 0o777, 0o600)
            p.guardar_razonamiento_chatgpt_oauth("auto", ruta)
            self.assertEqual(p.cargar_razonamiento_chatgpt_oauth(ruta), "auto")

    def test_razonamiento_invalido_no_sobrescribe_el_guardado(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "razonamiento.txt"
            p.guardar_razonamiento_chatgpt_oauth("high", ruta)
            for nivel in ("none", "minimal", "ultra", "", "HIGH", None, "high\\nmalicioso"):
                with self.subTest(nivel=nivel):
                    with self.assertRaises(ValueError):
                        p.guardar_razonamiento_chatgpt_oauth(nivel, ruta)
            self.assertEqual(p.cargar_razonamiento_chatgpt_oauth(ruta), "high")
            ruta.write_text("no-valido", encoding="utf-8")
            self.assertEqual(p.cargar_razonamiento_chatgpt_oauth(ruta), "auto")

    def test_razonamiento_es_independiente_del_motor_deepseek(self):
        with TemporaryDirectory() as carpeta:
            path_modelo = Path(carpeta) / "motor.txt"
            path_razonamiento = Path(carpeta) / "razonamiento.txt"
            p.guardar_razonamiento_chatgpt_oauth("max", path_razonamiento)
            self.assertEqual(p.cargar_motor_preferido(path_modelo),
                             p.MODELO_DEEPSEEK_PREDETERMINADO)
            self.assertEqual(p.cargar_razonamiento_chatgpt_oauth(path_razonamiento), "max")

    def test_sin_autorizacion_batch_ni_opencode(self):
        self.assertTrue(p.autorizar_pago_automatico(
            "openrouter::deepseek/deepseek-v4-flash-0731"))
        self.assertTrue(p.autorizar_pago_automatico("openrouter::openai/gpt-5"))
        self.assertFalse(p.autorizar_pago_automatico(
            "openrouter::deepseek/deepseek-v4.1-flash-1017:batch"))
        self.assertFalse(p.autorizar_pago_automatico("opencode/glm-5.3-flash-free"))
        self.assertFalse(p.autorizar_pago_automatico(""))


if __name__ == "__main__":
    unittest.main()
