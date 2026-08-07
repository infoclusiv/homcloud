import unittest

from documentos import (
    EXTENSIONES_CARGA_STREAMLIT,
    es_documento_soportado,
    modo_llmwhisperer_para_archivo,
    tipo_documento_para_archivo,
)


class DocumentosTests(unittest.TestCase):
    def test_extensiones_de_carga(self):
        self.assertEqual(EXTENSIONES_CARGA_STREAMLIT, ("pdf", "xlsx", "xls"))

    def test_pdf_usa_high_quality(self):
        self.assertTrue(es_documento_soportado("acta.pdf"))
        self.assertEqual(tipo_documento_para_archivo("acta.pdf"), "PDF")
        self.assertEqual(
            modo_llmwhisperer_para_archivo("acta.pdf"),
            "high_quality",
        )

    def test_excel_xlsx_usa_form(self):
        self.assertTrue(es_documento_soportado("acta.xlsx"))
        self.assertEqual(tipo_documento_para_archivo("acta.xlsx"), "Excel")
        self.assertEqual(
            modo_llmwhisperer_para_archivo("acta.xlsx"),
            "form",
        )

    def test_excel_xls_usa_form(self):
        self.assertTrue(es_documento_soportado("ACTA.XLS"))
        self.assertEqual(tipo_documento_para_archivo("ACTA.XLS"), "Excel")
        self.assertEqual(
            modo_llmwhisperer_para_archivo("ACTA.XLS"),
            "form",
        )

    def test_tipo_no_soportado_falla(self):
        self.assertFalse(es_documento_soportado("acta.csv"))
        with self.assertRaises(ValueError):
            modo_llmwhisperer_para_archivo("acta.csv")


if __name__ == "__main__":
    unittest.main()
