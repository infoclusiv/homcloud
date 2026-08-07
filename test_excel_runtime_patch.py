import unittest

from excel_runtime_patch import (
    _OLD_LLMWHISPERER_BLOCK,
    aplicar_soporte_excel,
)


class ExcelRuntimePatchTests(unittest.TestCase):
    def test_parche_habilita_excel_y_parser_dinamico(self):
        source = (
            _OLD_LLMWHISPERER_BLOCK
            + "\n"
            + '            type=["pdf"],\n'
            + 'page_title="PDF Batch Parser"\n'
            + '"El archivo adjunto es texto extraído de un PDF por LLMWhisperer."\n'
        )

        patched = aplicar_soporte_excel(source)

        self.assertIn('type=["pdf", "xlsx", "xls"]', patched)
        self.assertIn("modo_llmwhisperer_para_archivo", patched)
        self.assertIn("tipo_documento_para_archivo", patched)
        self.assertIn('page_title="Document Batch Parser"', patched)
        self.assertIn("documento PDF o Excel", patched)
        self.assertNotIn('mode="high_quality"', patched)


if __name__ == "__main__":
    unittest.main()
