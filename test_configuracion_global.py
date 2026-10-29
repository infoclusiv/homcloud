"""Pruebas locales sin credenciales de Firestore ni efectos sobre datos reales."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import configuracion_global as config
from retencion_local import candidatos_limpieza, inventario


class PreferenciasTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(config.validar_preferencias({}), {"procesos_predeterminados": 4, "retencion_dias": 7, "retencion_pdfs_dias": 3})

    def test_limites(self):
        for valor in (0, 21, True, 1.5, "nada"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                config.validar_preferencias({"procesos_predeterminados": valor})
        for dias in (0, 91, True, 2.5):
            with self.subTest(dias=dias), self.assertRaises(ValueError):
                config.validar_preferencias({"retencion_dias": dias})
        for dias in (0, 91, True, "no es numero"):
            with self.subTest(dias=dias), self.assertRaises(ValueError):
                config.validar_preferencias({"retencion_pdfs_dias": dias})

    def test_fallback_local(self):
        with TemporaryDirectory() as tmp, patch.object(config, "LOCAL_PATH", Path(tmp) / "prefs.json"), patch.object(config, "proyecto_configurado", return_value=None):
            config.guardar_preferencias({"procesos_predeterminados": 8, "retencion_dias": 14}, None)
            preferencias, revision, proyecto = config.leer_preferencias()
            self.assertEqual(preferencias["procesos_predeterminados"], 8)
            self.assertEqual(preferencias["retencion_dias"], 14)
            self.assertIsNone(revision)
            self.assertIsNone(proyecto)


class RetencionTests(unittest.TestCase):
    def test_inventario_y_lote_mas_reciente_protegido(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            viejo = base / "outputs" / "runs" / "viejo"
            nuevo = base / "outputs" / "runs" / "nuevo"
            viejo.mkdir(parents=True)
            nuevo.mkdir(parents=True)
            (viejo / "uno.csv").write_text("1", encoding="utf-8")
            (nuevo / "dos.csv").write_text("2", encoding="utf-8")
            import os
            import time
            antigua = time.time() - 30 * 86400
            for p in (viejo / "uno.csv", viejo):
                os.utime(p, (antigua, antigua))
            self.assertEqual(inventario(base)["archivos"], 2)
            self.assertIn(viejo, candidatos_limpieza(base, 7))
            self.assertNotIn(nuevo, candidatos_limpieza(base, 7))


if __name__ == "__main__":
    unittest.main()
