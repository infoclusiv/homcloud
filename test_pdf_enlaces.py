"""Pruebas locales sin Streamlit, Cloud Shell ni documentos reales."""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pdf_enlaces import publicar_pdf


class EnlacesPDFTests(unittest.TestCase):
    def test_enlace_abre_el_original_sin_duplicar_bytes(self):
        with TemporaryDirectory() as carpeta:
            root = Path(carpeta)
            original = root / "uploads" / "20261026_101010_abcdef" / "Acta ejemplo.pdf"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"%PDF-1.4\ncontenido")
            enlace = publicar_pdf(original, root)
            self.assertTrue(enlace.startswith("app/static/pdfs/"))
            self.assertTrue(enlace.endswith("/Acta ejemplo.pdf"))
            destino = root / enlace.removeprefix("app/")
            self.assertTrue(destino.exists())
            self.assertTrue(os.path.samefile(original, destino))
            self.assertEqual(publicar_pdf(original, root), enlace)
            secreto = root / "settings" / ".pdf_link_secret"
            self.assertEqual(len(secreto.read_bytes()), 32)
            self.assertFalse(secreto.stat().st_mode & 0o077)
            destino.unlink()
            self.assertEqual(original.read_bytes(), b"%PDF-1.4\ncontenido")

    def test_lotes_homonimos_no_comparten_enlace(self):
        with TemporaryDirectory() as carpeta:
            root = Path(carpeta)
            pdf1 = root / "uploads" / "lote_1" / "Mismo.pdf"
            pdf2 = root / "uploads" / "lote_2" / "Mismo.pdf"
            pdf1.parent.mkdir(parents=True)
            pdf2.parent.mkdir(parents=True)
            pdf1.write_bytes(b"PDF A")
            pdf2.write_bytes(b"PDF B")
            self.assertNotEqual(publicar_pdf(pdf1, root), publicar_pdf(pdf2, root))

    def test_rechaza_pdf_fuera_de_uploads_y_symlinks(self):
        with TemporaryDirectory() as carpeta:
            root = Path(carpeta)
            ruta_externa = root / "privado.pdf"
            ruta_externa.write_bytes(b"%PDF")
            self.assertEqual(publicar_pdf(ruta_externa, root), "")
            ruta = root / "uploads" / "lote" / "link.pdf"
            ruta.parent.mkdir(parents=True)
            ruta.symlink_to(ruta_externa)
            self.assertEqual(publicar_pdf(ruta, root), "")

    def test_copia_solo_si_no_es_posible_hardlink(self):
        with TemporaryDirectory() as carpeta:
            root = Path(carpeta)
            original = root / "uploads" / "20261026_010101_abcdef" / "Copia.pdf"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"%PDF fallback")
            with patch("pdf_enlaces.os.link", side_effect=OSError("cross-device")):
                enlace = publicar_pdf(original, root)
            destino = root / enlace.removeprefix("app/")
            self.assertEqual(original.read_bytes(), destino.read_bytes())
            self.assertFalse(os.path.samefile(original, destino))


if __name__ == "__main__":
    unittest.main()
