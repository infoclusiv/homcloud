"""Recuperación sin escritura de lotes interrumpidos o reintentos incompletos.

Lee CSV y metadata locales; no importa app_core ni toca APIs externas.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import re
import zipfile

RUN_RE = re.compile(r"^[a-zA-Z0-9_-]{6,80}$")
MAX_PROFUNDIDAD = 12


def validar_run_id(run_id: str) -> str:
    if not RUN_RE.fullmatch(str(run_id or "")):
        raise ValueError("Identificador de lote inválido.")
    return str(run_id)


def leer_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError, UnicodeError):
        return {}


def leer_csv(path: Path) -> list[dict]:
    if not path.is_file() or path.is_symlink():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def es_error_reintentable(fila: dict) -> bool:
    estado = str(fila.get("Estado") or "").casefold()
    return "error" in estado or "fall" in estado or "inesperado" in estado


def fusionar_filas(base: list[dict], nuevas: list[dict]) -> list[dict]:
    """Un reintento reemplaza por nombre sin descartar los PDF ya correctos."""
    resultado = {str(f.get("Archivo") or "").casefold(): dict(f) for f in base}
    for fila in nuevas:
        nombre = str(fila.get("Archivo") or "").casefold()
        if nombre:
            resultado[nombre] = dict(fila)
    return list(resultado.values())


def listar_lotes(base_dir: Path) -> list[str]:
    raiz = base_dir / "outputs" / "runs"
    if not raiz.is_dir():
        return []
    candidatos = []
    for p in raiz.iterdir():
        if not p.is_dir() or p.is_symlink() or not RUN_RE.fullmatch(p.name):
            continue
        if ((p / "resumen_resultados.csv").is_file()
            or (p / "resumen_resultados_parcial.csv").is_file()
            or (base_dir / "uploads" / p.name).is_dir()):
            candidatos.append(p)
    return [p.name for p in sorted(candidatos, key=lambda p: p.stat().st_mtime, reverse=True)]


def recuperar_lote(base_dir: Path, run_id: str, _vistos: set[str] | None = None) -> dict:
    run_id = validar_run_id(run_id)
    vistos = set(_vistos or ())
    if run_id in vistos or len(vistos) >= MAX_PROFUNDIDAD:
        raise ValueError("Ciclo o profundidad excesiva en lotes vinculados.")
    vistos.add(run_id)
    raiz = base_dir / "outputs" / "runs"
    directorio = raiz / run_id
    if not directorio.is_dir() or directorio.is_symlink():
        raise FileNotFoundError(f"No existe el lote {run_id}.")

    metadata = leer_json(directorio / "metadata_lote.json")
    metadata_combinado = leer_json(directorio / "metadata_resultado_combinado.json")
    parent_id = str(metadata.get("parent_run_id") or "").strip()
    if parent_id:
        validar_run_id(parent_id)
    csv_final = directorio / "resumen_resultados.csv"
    csv_parcial = directorio / "resumen_resultados_parcial.csv"
    es_final = csv_final.is_file()
    archivo = csv_final if es_final else csv_parcial
    filas_actuales = leer_csv(archivo)

    # Un CSV combinado ya incluye su base. No fusionar por segunda vez.
    if parent_id and not (es_final and metadata_combinado):
        base = recuperar_lote(base_dir, parent_id, vistos)
        filas_actuales = fusionar_filas(base["filas"], filas_actuales)

    # Si la sesión terminó antes de escribir la última fila, el PDF original
    # aún existe y debe quedar marcado para reintentar, no perderse.
    archivos_presentes = {
        str(f.get("Archivo") or "").casefold() for f in filas_actuales
    }
    uploads = base_dir / "uploads" / run_id
    if uploads.is_dir() and not uploads.is_symlink():
        for pdf in sorted(uploads.glob("*.pdf")):
            if pdf.is_symlink() or not pdf.is_file():
                continue
            if pdf.name.casefold() not in archivos_presentes:
                filas_actuales.append({
                    "Archivo": pdf.name,
                    "Estado": "Error no iniciado",
                    "Fase actual": "Interrumpido",
                    "Archivo AHK": "No generado",
                    "Error": "No se guardó el resultado antes de interrumpirse el lote.",
                })
                archivos_presentes.add(pdf.name.casefold())

    return {
        "run_id": run_id,
        "parent_run_id": parent_id,
        "run_outputs_dir": str(directorio),
        "run_uploads_dir": str(uploads),
        "filas": filas_actuales,
        "filas_error": [f for f in filas_actuales if es_error_reintentable(f)],
        "resumen_csv_path": str(archivo) if archivo.is_file() else "",
        "errores_csv_path": "",
        "zip_ahk_path": "",
        "es_resultado_combinado": bool(parent_id),
        "es_recuperacion_parcial": not es_final,
    }


def csv_recuperado_bytes(filas: list[dict]) -> bytes:
    campos = list(dict.fromkeys(
        campo for fila in filas for campo in fila.keys()
    ))
    salida = io.StringIO(newline="")
    if campos:
        writer = csv.DictWriter(salida, fieldnames=campos)
        writer.writeheader()
        writer.writerows(filas)
    return ("\ufeff" + salida.getvalue()).encode("utf-8")


def zip_recuperado_bytes(filas: list[dict], base_dir: Path) -> tuple[bytes, int]:
    """Reconstruye un ZIP desde AHK verificados de este directorio de trabajo."""
    raiz = (base_dir / "outputs" / "runs").resolve()
    salida = io.BytesIO()
    usados = set()
    total = 0
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zipf:
        for fila in filas:
            if not str(fila.get("Estado") or "").casefold() == "completado":
                continue
            ruta_str = str(fila.get("Archivo AHK") or "").strip()
            if not ruta_str or ruta_str == "No generado":
                continue
            ruta = Path(ruta_str)
            # Rutas relativas pueden venir de versiones antiguas.
            if not ruta.is_absolute():
                ruta = base_dir / ruta
            if ruta.is_symlink() or ruta.suffix.casefold() != ".ahk":
                continue
            try:
                resuelta = ruta.resolve(strict=True)
                if not resuelta.is_relative_to(raiz) or not resuelta.is_file():
                    continue
                nombre = resuelta.name
                if nombre.casefold() in usados:
                    continue
                zipf.write(resuelta, arcname=nombre)
                usados.add(nombre.casefold())
                total += 1
            except OSError:
                continue
    return salida.getvalue(), total
