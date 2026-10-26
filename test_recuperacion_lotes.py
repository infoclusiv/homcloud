"""Pruebas de resiliencia y privacidad: no requieren Streamlit, Firestore ni API."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
import zipfile

from recuperacion_lotes import (
    csv_recuperado_bytes,
    listar_lotes,
    recuperar_lote,
    validar_run_id,
    zip_recuperado_bytes,
)
from retencion_local import (
    candidatos_limpieza,
    inventario,
    limpiar_archivos_antiguos,
)


def escribir_filas(path: Path, filas: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)


class RecuperacionTests(unittest.TestCase):
    def test_lote_interrumpido_marca_pdf_sin_fila_y_recupera_zip(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "20261026_140000_abcd"
            output = base / "outputs" / "runs" / run_id
            uploads = base / "uploads" / run_id
            uploads.mkdir(parents=True)
            (uploads / "A.pdf").write_bytes(b"%PDF-1.4 A")
            (uploads / "B.pdf").write_bytes(b"%PDF-1.4 B")
            (uploads / "C.pdf").write_bytes(b"%PDF-1.4 C")
            ahk = output / "A.ahk"
            ahk.parent.mkdir(parents=True)
            ahk.write_text("MsgBox, A", encoding="utf-8")
            escribir_filas(output / "resumen_resultados_parcial.csv", [
                {"Archivo": "A.pdf", "Estado": "Completado", "Archivo AHK": str(ahk)},
                {"Archivo": "B.pdf", "Estado": "Error inesperado", "Archivo AHK": "No generado"},
            ])
            self.assertIn(run_id, listar_lotes(base))
            recuperado = recuperar_lote(base, run_id)
            self.assertEqual(len(recuperado["filas"]), 3)
            self.assertEqual(len(recuperado["filas_error"]), 2)
            fila_c = next(f for f in recuperado["filas"] if f["Archivo"] == "C.pdf")
            self.assertEqual(fila_c["Estado"], "Error no iniciado")
            self.assertIn(b"C.pdf", csv_recuperado_bytes(recuperado["filas"]))
            zip_data, total = zip_recuperado_bytes(recuperado["filas"], base)
            self.assertEqual(total, 1)
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                self.assertEqual(z.namelist(), ["A.ahk"])

    def test_recuperar_reintento_preserva_ahk_de_lote_padre(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            padre, hijo = "20261026_150000_abcd", "20261026_151000_abcd"
            base_out = base / "outputs" / "runs" / padre
            retry_out = base / "outputs" / "runs" / hijo
            base_out.mkdir(parents=True)
            retry_out.mkdir(parents=True)
            ahk_a = base_out / "A.ahk"
            ahk_b = retry_out / "B.ahk"
            ahk_a.write_text("MsgBox, A", encoding="utf-8")
            ahk_b.write_text("MsgBox, B", encoding="utf-8")
            escribir_filas(base_out / "resumen_resultados.csv", [
                {"Archivo": "A.pdf", "Estado": "Completado", "Archivo AHK": str(ahk_a)},
                {"Archivo": "B.pdf", "Estado": "Error OpenCode", "Archivo AHK": "No generado"},
            ])
            escribir_filas(retry_out / "resumen_resultados_parcial.csv", [
                {"Archivo": "B.pdf", "Estado": "Completado", "Archivo AHK": str(ahk_b)},
            ])
            (retry_out / "metadata_lote.json").write_text(
                json.dumps({"parent_run_id": padre}), encoding="utf-8"
            )
            recuperado = recuperar_lote(base, hijo)
            self.assertEqual(len(recuperado["filas"]), 2)
            self.assertEqual(len(recuperado["filas_error"]), 0)
            _, total = zip_recuperado_bytes(recuperado["filas"], base)
            self.assertEqual(total, 2)

    def test_run_id_protege_rutas_y_no_archiva_ahk_externos(self):
        with self.assertRaises(ValueError):
            validar_run_id("../fuera")
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            fuera = base / "fuera.ahk"
            fuera.write_text("Mensaje externo", encoding="utf-8")
            contenido, total = zip_recuperado_bytes([
                {"Archivo": "N.pdf", "Estado": "Completado", "Archivo AHK": str(fuera)}
            ], base)
            self.assertEqual(total, 0)
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                self.assertFalse(z.namelist())


class RetencionSeguraTests(unittest.TestCase):
    def test_hard_links_cuentan_una_vez(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            a = base / "uploads" / "loteA" / "A.pdf"
            b = base / "uploads" / "loteB" / "A.pdf"
            a.parent.mkdir(parents=True)
            b.parent.mkdir(parents=True)
            a.write_bytes(b"1234567890")
            os.link(a, b)
            uso = inventario(base)
            self.assertEqual(uso["bytes"], 10)
            self.assertEqual(uso["archivos"], 2)

    def test_no_limpia_lotes_protegidos_aunque_sean_antiguos(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            antiguo = base / "outputs" / "runs" / "20261001_120000_abcd"
            actual = base / "outputs" / "runs" / "20261026_120000_abcd"
            original = base / "uploads" / antiguo.name
            antiguo.mkdir(parents=True)
            actual.mkdir(parents=True)
            original.mkdir(parents=True)
            (antiguo / ".procesamiento_activo").write_text("1234")
            (original / "A.pdf").write_bytes(b"PDF")
            hace_mes = time.time() - 30 * 86400
            for p in (antiguo / ".procesamiento_activo", original / "A.pdf", antiguo, original):
                os.utime(p, (hace_mes, hace_mes))
            self.assertNotIn(antiguo, candidatos_limpieza(base, 7))
            self.assertNotIn(original, candidatos_limpieza(base, 7))
            borrados = limpiar_archivos_antiguos(base, 7)
            self.assertEqual(borrados, [])
            self.assertTrue((original / "A.pdf").is_file())


if __name__ == "__main__":
    unittest.main()
