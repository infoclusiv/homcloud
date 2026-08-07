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

    def test_catalogo_estandar_tiene_35_programas(self):
        self.assertEqual(len(PROGRAMAS_PLANES_DEFAULT), 35)

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

    def test_nuevos_programas_p1_permiten_vacio(self):
        casos = [
            "Especialización en Ciberseguridad",
            "Especialización en Neuropsicología de la Educación",
            "Seguridad y Salud en el Trabajo Virtual",
            "Maestría en Gerencia de Proyectos",
            "Trabajo Social Virtual",
            "Especialización en Analítica y Big Data",
        ]
        for programa in casos:
            with self.subTest(programa=programa):
                self.assertEqual(
                    evaluar_plan(programa, "P1", self.mapa),
                    "correcto",
                )
                self.assertEqual(
                    evaluar_plan(programa, "", self.mapa),
                    "correcto",
                )
                self.assertEqual(
                    evaluar_plan(programa, "P2", self.mapa),
                    "incorrecto",
                )

    def test_pregrado_sst_reconoce_virtual_y_nombre_corto(self):
        casos = [
            "Seguridad y salud en el trabajo - virtual",
            "SEGURIDAD Y SALUD EN EL TRABAJO",
        ]
        for programa in casos:
            with self.subTest(programa=programa):
                self.assertEqual(
                    evaluar_plan(programa, "Plan 1", self.mapa),
                    "correcto",
                )
                self.assertEqual(
                    evaluar_plan(programa, "", self.mapa),
                    "correcto",
                )

    def test_especializacion_gerencia_sst_es_p2_y_vacio_incorrecto(self):
        casos = [
            "Especialización en Gerencia de la Seguridad y Salud en el Trabajo Virtual",
            "ESP GCIA SEG SALUD EN TRA VIRT",
            "Especialización en Seguridad y Salud en el Trabajo",
        ]
        for programa in casos:
            with self.subTest(programa=programa):
                self.assertEqual(
                    evaluar_plan(programa, "P2", self.mapa),
                    "correcto",
                )
                self.assertEqual(
                    evaluar_plan(programa, "", self.mapa),
                    "incorrecto",
                )
                self.assertEqual(
                    evaluar_plan(programa, "P1", self.mapa),
                    "incorrecto",
                )

    def test_marketing_conserva_p2_y_vacio_incorrecto(self):
        self.assertEqual(
            evaluar_plan(
                "Marketing y Negocios Internacionales",
                "P2",
                self.mapa,
            ),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan(
                "Marketing y Negocios Internacionales",
                "",
                self.mapa,
            ),
            "incorrecto",
        )

    def test_analitica_virtual_se_reconoce(self):
        self.assertEqual(
            evaluar_plan(
                "ESPECIALIZACION EN ANALITICA VIRTUAL Y BIG DATA",
                "",
                self.mapa,
            ),
            "correcto",
        )

    def test_migracion_v2_separa_sst_y_preserva_alias_personalizado(self):
        legado = [
            {
                "Programa al que aspira": "Especialización en Seguridad y Salud en el Trabajo",
                "Plan": "P2",
                "Alias": (
                    "Esp seg y salud trabajo; Especialización SST; "
                    "Seguridad y Salud en el Trabajo; Alias SST personalizado"
                ),
                CAMPO_PERMITIR_PLAN_VACIO: False,
            },
            {
                "Programa al que aspira": "Marketing y Negocios Internacionales",
                "Plan": "P2",
                "Alias": "Marketing y negocios",
                CAMPO_PERMITIR_PLAN_VACIO: False,
            },
        ]

        with tempfile.TemporaryDirectory() as carpeta:
            path = Path(carpeta) / "programas_planes.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "programas": legado,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            migrados = cargar_programas_planes(path)
            mapa = construir_mapa_programas_planes(migrados)
            persistido = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(migrados), 35)
        self.assertEqual(
            persistido["version"],
            PROGRAMAS_PLANES_CONFIG_VERSION,
        )
        self.assertEqual(
            evaluar_plan("Seguridad y Salud en el Trabajo", "P1", mapa),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan("Seguridad y Salud en el Trabajo", "P2", mapa),
            "incorrecto",
        )
        self.assertEqual(
            evaluar_plan(
                "Especialización en Seguridad y Salud en el Trabajo",
                "P2",
                mapa,
            ),
            "correcto",
        )
        self.assertEqual(
            evaluar_plan("ESP GCIA SEG SALUD EN TRA VIRT", "", mapa),
            "incorrecto",
        )
        self.assertEqual(
            evaluar_plan("Alias SST personalizado", "P2", mapa),
            "correcto",
        )

    def test_campo_plan_vacio_esta_activo_en_23_programas(self):
        cantidad = sum(
            1
            for fila in PROGRAMAS_PLANES_DEFAULT
            if fila[CAMPO_PERMITIR_PLAN_VACIO]
        )
        self.assertEqual(cantidad, 23)


if __name__ == "__main__":
    unittest.main()
