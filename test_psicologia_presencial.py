import json
from pathlib import Path
import tempfile
import unittest

from programas_planes import (
    CAMPO_PERMITIR_PLAN_VACIO,
    PROGRAMAS_PLANES_CONFIG_VERSION,
    PROGRAMAS_PLANES_DEFAULT,
    construir_mapa_programas_planes,
    cargar_programas_planes,
    evaluar_plan,
)


class PsicologiaPresencialTests(unittest.TestCase):
    def test_psicologia_presencial_es_alias_de_psicologia_p4(self):
        mapa = construir_mapa_programas_planes(PROGRAMAS_PLANES_DEFAULT)

        casos_correctos = [
            ("Psicología", "P4"),
            ("PSICOLOGIA", "Plan 4"),
            ("Psicología Presencial", "P4"),
            ("PSICOLOGIA PRESENCIAL", "4"),
        ]
        for programa, plan in casos_correctos:
            with self.subTest(programa=programa, plan=plan):
                self.assertEqual(evaluar_plan(programa, plan, mapa), "correcto")

        self.assertEqual(
            evaluar_plan("Psicología Presencial", "P3", mapa),
            "incorrecto",
        )
        self.assertEqual(
            evaluar_plan("Psicología Presencial", "", mapa),
            "incorrecto",
        )

    def test_configuracion_v3_migra_alias_psicologia_presencial_a_v4(self):
        legado = [
            {
                "Programa al que aspira": "Psicología",
                "Plan": "P4",
                "Alias": "Alias Psicología Personalizado",
                CAMPO_PERMITIR_PLAN_VACIO: False,
            }
        ]

        with tempfile.TemporaryDirectory() as carpeta:
            path = Path(carpeta) / "programas_planes.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "programas": legado,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            migrados = cargar_programas_planes(path)
            mapa = construir_mapa_programas_planes(migrados)
            persistido = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(PROGRAMAS_PLANES_CONFIG_VERSION, 4)
        self.assertEqual(persistido["version"], 4)
        self.assertEqual(
            evaluar_plan("PSICOLOGIA PRESENCIAL", "P4", mapa),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan("Alias Psicología Personalizado", "P4", mapa),
            "correcto",
        )


if __name__ == "__main__":
    unittest.main()
