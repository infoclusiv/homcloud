"""Contratos de seguridad y selección del reintento sin credenciales ni APIs."""
import unittest

from reintentos_proveedor import (
    PROVEEDORES_REINTENTO,
    causas_reintentables,
    proveedor_desde_modelo,
    requisitos_reintento,
)


def evaluar(proveedor: str, modelo: str, **changes) -> list[str]:
    parametros = {
        "hay_llmwhisperer": True,
        "prompts_validos": True,
        "ajustes_validos": True,
        "opencode_instalado": True,
        "openrouter_con_clave": True,
        "openrouter_modelo_valido": True,
        "openrouter_es_pago": False,
        "pago_confirmado": False,
        "oauth_actas_autorizadas": True,
        "oauth_sesion_valida": True,
        "oauth_modelo_disponible": True,
    }
    parametros.update(changes)
    return requisitos_reintento(proveedor, modelo, **parametros)


class ReintentosProveedorTests(unittest.TestCase):
    def test_proveedor_no_se_infiere_del_selector_principal(self):
        self.assertEqual(proveedor_desde_modelo("opencode/modelo"), "OpenCode")
        self.assertEqual(proveedor_desde_modelo("openrouter::openrouter/free"), "OpenRouter")
        self.assertEqual(proveedor_desde_modelo("chatgpt::gpt-6.1-sol"), "ChatGPT OAuth")

    def test_exige_escoger_proveedor(self):
        self.assertEqual(len(PROVEEDORES_REINTENTO), 4)
        self.assertTrue(evaluar(PROVEEDORES_REINTENTO[0], ""))

    def test_opencode_admite_default_y_valida_modelo_manual(self):
        self.assertFalse(evaluar("OpenCode", ""))
        self.assertFalse(evaluar("OpenCode", "anthropic/claude"))
        self.assertTrue(evaluar("OpenCode", "in válido"))
        self.assertTrue(evaluar("OpenCode", "openrouter::openrouter/free"))
        self.assertTrue(evaluar("OpenCode", "", opencode_instalado=False))

    def test_openrouter_requiere_clave_y_modelo_no_batch(self):
        self.assertFalse(evaluar("OpenRouter", "openrouter::openrouter/free"))
        self.assertTrue(evaluar("OpenRouter", "openrouter::openrouter/free", openrouter_con_clave=False))
        self.assertTrue(evaluar("OpenRouter", "openrouter::vendor/model:batch"))
        self.assertTrue(evaluar("OpenRouter", "openrouter::vendor/invalido", openrouter_modelo_valido=False))

    def test_modelo_pago_necesita_confirmacion(self):
        self.assertTrue(evaluar("OpenRouter", "openrouter::vendor/model", openrouter_es_pago=True))
        self.assertFalse(evaluar("OpenRouter", "openrouter::vendor/model", openrouter_es_pago=True, pago_confirmado=True))

    def test_oauth_requiere_autorizacion_sesion_y_modelo_real(self):
        self.assertFalse(evaluar("ChatGPT OAuth", "chatgpt::gpt-6.1-sol"))
        self.assertTrue(evaluar("ChatGPT OAuth", "chatgpt::gpt-6.1-sol", oauth_actas_autorizadas=False))
        self.assertTrue(evaluar("ChatGPT OAuth", "chatgpt::gpt-6.1-sol", oauth_sesion_valida=False))
        self.assertTrue(evaluar("ChatGPT OAuth", "chatgpt::gpt-6.1-sol", oauth_modelo_disponible=False))

    def test_requisitos_globales(self):
        self.assertEqual(len(evaluar("OpenCode", "", hay_llmwhisperer=False, prompts_validos=False, ajustes_validos=False)), 3)

    def test_resumen_de_causas_no_devuelve_textos_privados(self):
        rows = [
            {"Estado": "Error OpenCode", "Error": "HTTP 429 token secreto"},
            {"Estado": "Error LLMWhisperer", "Error": "informacion privada"},
            {"Estado": "Error timeout lote", "Error": ""},
            {"Estado": "Error JSON OpenCode", "Error": ""},
            {"Estado": "Error inesperado", "Error": ""},
        ]
        motivos = causas_reintentables(rows)
        self.assertEqual(sum(motivos.values()), 5)
        self.assertEqual(motivos["Límite de uso o solicitudes"], 1)
        self.assertNotIn("token secreto", str(motivos))
        self.assertNotIn("informacion privada", str(motivos))


if __name__ == "__main__":
    unittest.main()
