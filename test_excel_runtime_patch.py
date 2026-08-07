import unittest

from excel_runtime_patch import (
    _OLD_HEADER_MARKUP,
    _OLD_HEADER_STYLE_BLOCK,
    _OLD_LLMWHISPERER_BLOCK,
    _OLD_STATUS_CHIP_RENDERER,
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

    def test_parche_reemplaza_encabezado_real_y_elimina_markdown_multilinea(self):
        source = (
            _OLD_LLMWHISPERER_BLOCK
            + "\n"
            + _OLD_HEADER_STYLE_BLOCK
            + "\n"
            + _OLD_STATUS_CHIP_RENDERER
            + "\n"
            + _OLD_HEADER_MARKUP
            + "\n"
            + '            type=["pdf"],\n'
            + 'page_title="PDF Batch Parser"\n'
        )

        patched = aplicar_soporte_excel(source)

        self.assertNotIn(_OLD_STATUS_CHIP_RENDERER, patched)
        self.assertNotIn(_OLD_HEADER_MARKUP, patched)
        self.assertIn("st.html(header_html)", patched)
        self.assertIn('<div class="status-chip"><span class="label">', patched)
        self.assertIn("padding: 0.72rem 1rem;", patched)
        self.assertNotIn(r'<div class=\"app-shell\">', patched)


if __name__ == "__main__":
    unittest.main()
