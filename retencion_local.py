"""Inventario y borrado manual conservador de documentos locales.

Nunca toca Firestore, credenciales, archivos fuera de las carpetas definidas ni
lotes con marcador de actividad. Distingue hard links para estimar uso físico.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

CARPETAS = ("uploads", "outputs/runs", "static/pdfs", "static/exports")
MARCADOR_ACTIVIDAD = ".procesamiento_activo"


def inventario(base_dir: Path) -> dict:
    total = 0
    archivos = 0
    por_carpeta = {}
    inodos_contados: set[tuple[int, int]] = set()
    for carpeta in CARPETAS:
        ruta = base_dir / carpeta
        subtotal, cantidad, enlaces_reutilizados = 0, 0, 0
        if ruta.is_dir() and not ruta.is_symlink():
            for archivo in ruta.rglob("*"):
                if not archivo.is_file() or archivo.is_symlink():
                    continue
                try:
                    estadisticas = archivo.stat()
                    inodo = (estadisticas.st_dev, estadisticas.st_ino)
                    cantidad += 1
                    if inodo in inodos_contados:
                        enlaces_reutilizados += 1
                        continue
                    inodos_contados.add(inodo)
                    subtotal += estadisticas.st_size
                except OSError:
                    continue
        por_carpeta[carpeta] = {
            "bytes": subtotal,
            "archivos": cantidad,
            "hardlinks_reutilizados": enlaces_reutilizados,
        }
        total += subtotal
        archivos += cantidad
    return {"bytes": total, "archivos": archivos, "carpetas": por_carpeta}


def lotes_protegidos(base_dir: Path, adicionales: set[str] | None = None) -> set[str]:
    protegidos = set(adicionales or ())
    raiz = base_dir / "outputs" / "runs"
    if not raiz.is_dir() or raiz.is_symlink():
        return protegidos
    lotes = [p for p in raiz.iterdir() if p.is_dir() and not p.is_symlink()]
    if lotes:
        protegidos.add(max(lotes, key=lambda p: p.stat().st_mtime).name)
    for lote in lotes:
        if (lote / MARCADOR_ACTIVIDAD).is_file():
            protegidos.add(lote.name)
    return protegidos


def _seguro_y_antiguo(path: Path, umbral: float) -> bool:
    if path.is_symlink() or not (path.is_file() or path.is_dir()):
        return False
    try:
        contenidos = [path]
        if path.is_dir():
            contenidos.extend(path.rglob("*"))
        if any(p.is_symlink() for p in contenidos):
            return False
        return max(p.stat().st_mtime for p in contenidos) < umbral
    except OSError:
        return False


def candidatos_limpieza(base_dir: Path, dias: int, protegidos: set[str] | None = None) -> list[Path]:
    if isinstance(dias, bool) or not 1 <= int(dias) <= 90:
        raise ValueError("La retención debe estar entre 1 y 90 días.")
    protegidos_actuales = lotes_protegidos(base_dir, protegidos)
    umbral = (datetime.now(timezone.utc) - timedelta(days=int(dias))).timestamp()
    candidatos = []
    for carpeta in CARPETAS:
        raiz = base_dir / carpeta
        if not raiz.is_dir() or raiz.is_symlink():
            continue
        for ruta in raiz.iterdir():
            if ruta.name in protegidos_actuales:
                continue
            if _seguro_y_antiguo(ruta, umbral):
                candidatos.append(ruta)
    return candidatos


def limpiar_archivos_antiguos(
    base_dir: Path, dias: int, protegidos: set[str] | None = None,
) -> list[str]:
    # Escanear una vez evita coste cuadrático en volúmenes grandes.
    candidatos = candidatos_limpieza(base_dir, dias, protegidos)
    umbral = (datetime.now(timezone.utc) - timedelta(days=int(dias))).timestamp()
    borrados = []
    proteccion_inicial = lotes_protegidos(base_dir, protegidos)
    for ruta in candidatos:
        # Revalidar modificacion y marca del propio lote sin re-escanear
        # TODOS los lotes en cada iteración.
        if ruta.name in proteccion_inicial:
            continue
        if ruta.is_dir() and (ruta / MARCADOR_ACTIVIDAD).exists():
            continue
        if not _seguro_y_antiguo(ruta, umbral):
            continue
        if ruta.is_dir():
            shutil.rmtree(ruta)
        elif ruta.is_file():
            ruta.unlink()
        borrados.append(str(ruta.relative_to(base_dir)))
    return borrados
