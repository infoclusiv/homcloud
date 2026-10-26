"""Inventario y limpieza explícita de artefactos locales; nunca borra lotes recientes o activos."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

CARPETAS = ("uploads", "outputs/runs", "static/pdfs", "static/exports")


def inventario(base_dir: Path) -> dict:
    total = 0
    archivos = 0
    por_carpeta = {}
    for carpeta in CARPETAS:
        ruta = base_dir / carpeta
        subtotal, cantidad = 0, 0
        if ruta.is_dir() and not ruta.is_symlink():
            for archivo in ruta.rglob("*"):
                if archivo.is_file() and not archivo.is_symlink():
                    try:
                        subtotal += archivo.stat().st_size
                        cantidad += 1
                    except OSError:
                        continue
        por_carpeta[carpeta] = {"bytes": subtotal, "archivos": cantidad}
        total += subtotal
        archivos += cantidad
    return {"bytes": total, "archivos": archivos, "carpetas": por_carpeta}


def candidatos_limpieza(base_dir: Path, dias: int, protegidos: set[str] | None = None) -> list[Path]:
    if not 1 <= int(dias) <= 90:
        raise ValueError("La retención debe estar entre 1 y 90 días.")
    protegidos = set(protegidos or ())
    umbral = (datetime.now(timezone.utc) - timedelta(days=int(dias))).timestamp()
    runs = base_dir / "outputs" / "runs"
    if runs.is_dir():
        recientes = [p for p in runs.iterdir() if p.is_dir() and not p.is_symlink()]
        if recientes:
            protegidos.add(max(recientes, key=lambda p: p.stat().st_mtime).name)

    candidatos = []
    for carpeta in CARPETAS:
        raiz = base_dir / carpeta
        if not raiz.is_dir() or raiz.is_symlink():
            continue
        for ruta in raiz.iterdir():
            if ruta.is_symlink() or not (ruta.is_dir() or ruta.is_file()):
                continue
            if ruta.name in protegidos:
                continue
            try:
                # Evita borrar un lote modificado recientemente aunque su directorio sea antiguo.
                contenidos = [ruta, *ruta.rglob("*")] if ruta.is_dir() else [ruta]
                if any(p.is_symlink() for p in contenidos):
                    continue
                ultima_modificacion = max(p.stat().st_mtime for p in contenidos)
                if ultima_modificacion < umbral:
                    candidatos.append(ruta)
            except OSError:
                continue
    return candidatos


def limpiar_archivos_antiguos(base_dir: Path, dias: int, protegidos: set[str] | None = None) -> list[str]:
    borrados = []
    for ruta in candidatos_limpieza(base_dir, dias, protegidos):
        # Comprobar de nuevo en el momento de eliminación.
        if ruta not in candidatos_limpieza(base_dir, dias, protegidos):
            continue
        if ruta.is_dir():
            shutil.rmtree(ruta)
        elif ruta.is_file():
            ruta.unlink()
        borrados.append(str(ruta.relative_to(base_dir)))
    return borrados
