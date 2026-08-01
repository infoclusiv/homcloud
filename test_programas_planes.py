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
    normalizar_programa,
)


class ProgramasPlanesTests(unittest.TestCase):
    def setUp(self):
        self.mapa = construir_mapa_programas_planes(PROGRAMAS_PLANES_DEFAULT)

    def test_catalogo_estandar_tiene_29_programas(self):
        self.assertEqual(len(PROGRAMAS_PLANES_DEFAULT), 29)

    def test_variantes_de_tildes_y_virtual_se_reconocen(self):
        self.assertEqual(
            normalizar_programa("administraciòn de empresas virtual"),
            normalizar_programa("Administración de Empresas Virtual"),
        )
        self.assertEqual(
            evaluar_plan(
                "administracion de empresas virtual",
                "Plan 1",
                self.mapa,
            ),
            "correcto",
        )

    def test_programa_p1_permite_plan_vacio_y_rechaza_p2(self):
        self.assertEqual(
            evaluar_plan("Administración de Empresas", "", self.mapa),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan("Administración de Empresas", "P1", self.mapa),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan("Administración de Empresas", "P2", self.mapa),
            "incorrecto",
        )

    def test_humanidades_conserva_p2_y_permite_vacio(self):
        self.assertEqual(
            evaluar_plan(
                "Licenciatura en Humanidades y Lengua Castellana",
                "P2",
                self.mapa,
            ),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan(
                "Licenciatura en Humanidades y Lengua Castellana",
                "",
                self.mapa,
            ),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan(
                "Licenciatura en Humanidades y Lengua Castellana",
                "P1",
                self.mapa,
            ),
            "incorrecto",
        )

    def test_programa_anterior_no_permite_plan_vacio(self):
        self.assertEqual(
            evaluar_plan("Psicología", "", self.mapa),
            "incorrecto",
        )
        self.assertEqual(
            evaluar_plan("Psicología", "P4", self.mapa),
            "correcto",
        )

    def test_alias_de_usuario_se_reconocen(self):
        casos = [
            ("de software", "P1"),
            ("adminsitración financiera", ""),
            ("financiera virtual", "1"),
            ("esp en marketing digital vir", "P1"),
            ("esp gerencia de proyectos vir", ""),
            ("licenciatura en infantil", "P1"),
        ]
        for programa, plan in casos:
            with self.subTest(programa=programa, plan=plan):
                self.assertEqual(
                    evaluar_plan(programa, plan, self.mapa),
                    "correcto",
                )

    def test_migracion_agrega_programas_y_preserva_humanidades_p2(self):
        legado = [
            {
                "Programa al que aspira": "Psicología",
                "Plan": "P4",
                "Alias": "Psico",
            },
            {
                "Programa al que aspira": "Licenciatura en Educación Infantil",
                "Plan": "P1",
                "Alias": "Lic educación infantil",
            },
            {
                "Programa al que aspira": "Licenciatura en Humanidades y Lengua Castellana",
                "Plan": "P2",
                "Alias": "Lic humanidades",
            },
        ]

        with tempfile.TemporaryDirectory() as carpeta:
            path = Path(carpeta) / "programas_planes.json"
            path.write_text(
                json.dumps({"programas": legado}, ensure_ascii=False),
                encoding="utf-8",
            )

            migrados = cargar_programas_planes(path)
            mapa = construir_mapa_programas_planes(migrados)
            persistido = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(migrados), 29)
        self.assertEqual(
            persistido["version"],
            PROGRAMAS_PLANES_CONFIG_VERSION,
        )
        self.assertEqual(
            evaluar_plan("Psico", "P4", mapa),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan(
                "Licenciatura en Humanidades y Lengua Castellana",
                "P2",
                mapa,
            ),
            "correcto",
        )
        self.assertTrue(
            mapa[
                normalizar_programa(
                    "Licenciatura en Humanidades y Lengua Castellana"
                )
            ]["permitir_plan_vacio"]
        )

    def test_campo_plan_vacio_esta_activo_en_17_programas(self):
        cantidad = sum(
            1
            for fila in PROGRAMAS_PLANES_DEFAULT
            if fila[CAMPO_PERMITIR_PLAN_VACIO]
        )
        self.assertEqual(cantidad, 17)


if __name__ == "__main__":
    unittest.main()
