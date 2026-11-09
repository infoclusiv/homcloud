"""Prueba de integridad de los parches dinámicos de app.py sin lanzar Streamlit.

app.py reescribe fragmentos de app_core.py antes de ejecutarlo. Esta prueba
detecta cambios incompatibles en los marcadores de parche, y comprueba que
la fuente reescrita compila como Python.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


def extraer_constantes() -> dict[str, str]:
    arbol = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    resultado = {}
    for nodo in arbol.body:
        if not isinstance(nodo, ast.Assign):
            continue
        for target in nodo.targets:
            if isinstance(target, ast.Name) and (
                target.id.startswith("_OLD_") or target.id.startswith("_NEW_")
            ):
                try:
                    valor = ast.literal_eval(nodo.value)
                except (ValueError, TypeError):
                    continue
                if isinstance(valor, str):
                    resultado[target.id] = valor
    return resultado


class TransformacionStreamlitTests(unittest.TestCase):
    def test_todos_los_marcadores_existen_y_resultado_compila(self):
        source = (ROOT / "app_core.py").read_text(encoding="utf-8")
        variables = extraer_constantes()
        reemplazos = (
            ("COMPLETION_BLOCK", 1),
            ("COLUMN_ORDER_BLOCK", 1),
            ("OPERATIONAL_CONFIG_MARKER", 1),
            ("CONCURRENCY_LIMIT_LINE", 1),
            ("PARALLEL_CONFIG_BLOCK", 1),
            ("RESULTS_TABLE_LINE", 2),
            ("ERROR_TABLE_LINE", 2),
        )
        # Los dos primeros y el resto se aplican en este orden desde app.py.
        # No ejecutamos la app ni conectamos a ningún proveedor externo.
        for sufijo, esperado in reemplazos:
            anterior = variables[f"_OLD_{sufijo}"]
            nuevo = variables.get(f"_NEW_{sufijo}")
            if sufijo == "OPERATIONAL_CONFIG_MARKER":
                nuevo = variables["_NEW_OPERATIONAL_CONFIG_BLOCK"]
            self.assertIsNotNone(nuevo, sufijo)
            self.assertEqual(source.count(anterior), esperado, sufijo)
            source = source.replace(anterior, nuevo, esperado)

        antiguo = 'with st.expander("Ver detalle del último procesamiento", expanded=False):'
        nuevo = 'with st.expander("Ver detalle del último procesamiento", expanded=True):'
        self.assertEqual(source.count(antiguo), 1)
        source = source.replace(antiguo, nuevo, 1)
        # El código real aplica DESPUÉS el parche de Excel. Comprobar la
        # cadena completa evita que un cambio de encabezado rompa Streamlit
        # aun cuando el módulo compilaba en las pruebas parciales.
        from excel_runtime_patch import aplicar_soporte_excel
        source = aplicar_soporte_excel(source)
        self.assertIn("st.html(header_html)", source)
        self.assertIn('type=["pdf", "xlsx", "xls"]', source)
        self.assertIn('construir_estado_chip("OpenRouter"', source)
        self.assertIn("pages/05_Programas_y_planes.py", source)
        self.assertIn("pages/06_Configuracion_operativa.py", source)
        self.assertNotIn("with col_programas:", source)
        self.assertIn("st.sidebar.expander", source)
        self.assertIn("validacion_openrouter = verificar_api_key_openrouter(", source)
        self.assertIn("api_key=obtener_api_key_openrouter()", source)
        self.assertNotIn(
            'st.session_state.get("openrouter_api_key_sesion") or obtener_api_key_openrouter()',
            source,
        )
        self.assertTrue((ROOT / "pages" / "05_Programas_y_planes.py").is_file())
        self.assertTrue((ROOT / "pages" / "06_Configuracion_operativa.py").is_file())
        compile(source, str(ROOT / "app_core.py"), "exec")


if __name__ == "__main__":
    unittest.main()
