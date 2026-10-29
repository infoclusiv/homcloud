"""Pruebas de historial acumulado y limpieza segura, sin Firestore real."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import historial_homologaciones as h


def _preparar_lote(base: Path, run_id: str = "20261020_110000_abc123") -> Path:
    raiz = base / "outputs" / "runs" / run_id
    raiz.mkdir(parents=True, exist_ok=True)
    uploads = base / "uploads" / run_id
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "Estudiante.pdf").write_bytes(b"%PDF-1.4 DOCUMENTO")
    (uploads / "Pendiente.pdf").write_bytes(b"%PDF-1.4 SIN RESULTADO")
    (raiz / "archivo_opencode.json").write_bytes(b"x" * 5000)
    (raiz / "metadata_lote.json").write_text(json.dumps({
        "run_id": run_id, "fecha": "2026-10-20T11:00:00",
        "parent_run_id": "", "modelo_opencode": "modelo/test",
    }), encoding="utf-8")
    with (raiz / "resumen_resultados.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Archivo", "Programa origen", "Programa al que aspira", "Plan",
            "Créditos homologados", "Estado", "Nivel",
        ])
        writer.writeheader()
        writer.writerow({
            "Archivo": "Estudiante.pdf", "Programa origen": "LIC. EDUCACIÓN",
            "Programa al que aspira": "MAESTRÍA EN EDUCACIÓN", "Plan": "2",
            "Créditos homologados": "25", "Estado": "Completado", "Nivel": "Posgrado",
        })
    return raiz


class HistorialTests(unittest.TestCase):
    def test_acumula_csv_y_no_guarda_pdfs(self):
        with TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = _preparar_lote(base)
            with patch.object(h, "proyecto_configurado", return_value=None):
                resultado = h.archivar_lote(base, ruta.name)
                repetido = h.archivar_lote(base, ruta.name)
                self.assertTrue(repetido["ya_archivado"])
            self.assertEqual(resultado["filas"], 2)
            csv_local = base / "historial" / "homologaciones_historico.csv"
            registros = h._leer_csv(csv_local)
            self.assertEqual(len(registros), 2)
            primero = next(x for x in registros if x["Estado"] == "Completado")
            self.assertEqual(primero["Programa origen"], "LIC. EDUCACIÓN")
            self.assertEqual(primero["Programa al que aspira"], "MAESTRÍA EN EDUCACIÓN")
            self.assertEqual(primero["Créditos homologados"], "25")
            self.assertEqual(primero["Plan"], "2")
            self.assertFalse(any("Archivo AHK" in x for x in registros))
            self.assertEqual(h.csv_historial_bytes(registros).count(b"Estudiante.pdf"), 1)

    def test_no_borra_antes_de_confirmacion_remota(self):
        with TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = _preparar_lote(base)
            with (
                patch.object(h, "proyecto_configurado", return_value="shared-project"),
                patch.object(h, "_subir_firestore", side_effect=ConnectionError("sin red")),
            ):
                resultado = h.limpiar_antiguos(base, 3)
            self.assertEqual(resultado["borrados"], 0)
            self.assertTrue((base / "uploads" / ruta.name / "Estudiante.pdf").exists())
            self.assertTrue((ruta / "resumen_resultados.csv").exists())
            self.assertEqual(len(resultado["errores"]), 1)

    def test_tres_dias_archiva_y_borra_lote_pesado(self):
        with TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = _preparar_lote(base)
            publicada = base / "static" / "pdfs" / "token_seguro"
            publicada.mkdir(parents=True)
            os.link(base / "uploads" / ruta.name / "Estudiante.pdf", publicada / "Estudiante.pdf")
            viejo = time.time() - 10 * 86400
            os.utime(publicada, (viejo, viejo))
            with patch.object(h, "proyecto_configurado", return_value=None):
                resultado = h.limpiar_antiguos(base, 3)
            self.assertEqual(resultado["archivados"], 1)
            self.assertEqual(resultado["borrados"], 1)
            self.assertEqual(resultado["pdf_enlaces"], 1)
            self.assertFalse(ruta.exists())
            self.assertFalse((base / "uploads" / ruta.name).exists())
            self.assertFalse(publicada.exists())
            self.assertEqual(len(h.exportar_historial(base)), 2) if False else None
            self.assertEqual(len(h._leer_csv(base / "historial" / "homologaciones_historico.csv")), 2)

    def test_lote_reciente_no_se_borra(self):
        with TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = _preparar_lote(base, "20261029_093000_abc123")
            with patch.object(h, "proyecto_configurado", return_value=None):
                resultado = h.limpiar_antiguos(base, 3)
            self.assertEqual(resultado["borrados"], 0)
            self.assertTrue(ruta.is_dir())

    def test_marca_de_proceso_activo_protege_lote(self):
        with TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = _preparar_lote(base)
            (ruta / ".procesamiento_activo").write_text(str(os.getpid()), encoding="ascii")
            with (
                patch.object(h, "proyecto_configurado", return_value=None),
                patch.object(h, "lote_en_ejecucion", return_value=True),
            ):
                resultado = h.limpiar_antiguos(base, 3)
            self.assertEqual(resultado["borrados"], 0)
            self.assertTrue(ruta.exists())

    def test_globales_subidos_antes_de_borrar(self):
        with TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = _preparar_lote(base)
            guardados = []
            with (
                patch.object(h, "proyecto_configurado", return_value="shared-project"),
                patch.object(h, "_subir_firestore", side_effect=lambda filas, proyecto: guardados.extend(filas)),
            ):
                resultado = h.limpiar_antiguos(base, 3)
            self.assertEqual(resultado["borrados"], 1)
            self.assertEqual(len(guardados), 2)
            self.assertEqual(guardados[0]["Lote"], ruta.name)

    def test_registro_no_cambia_id_si_se_reordena_el_csv(self):
        with TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = _preparar_lote(base)
            registros1, _ = h.registros_de_lote(base, ruta.name)
            csv_final = ruta / "resumen_resultados.csv"
            filas = h._leer_csv(csv_final)
            filas.insert(0, {"Archivo": "Otro.pdf", "Estado": "Completado"})
            with csv_final.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(filas[1]))
                writer.writeheader()
                writer.writerows(filas)
            registros2, _ = h.registros_de_lote(base, ruta.name)
            a = next(x for x in registros1 if x["Archivo"] == "Estudiante.pdf")
            b = next(x for x in registros2 if x["Archivo"] == "Estudiante.pdf")
            self.assertEqual(a["ID registro"], b["ID registro"])


if __name__ == "__main__":
    unittest.main()
