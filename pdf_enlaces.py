"""Publicación de PDF originales para enlaces de la columna Archivo.

No se duplican los bytes de los PDF en Cloud Shell si el filesystem admite
hard links (caso normal para directorios del mismo homcloud). Los enlaces son
capabilities: NO compartir las URLs ni exponer Web Preview al público.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets
import shutil

CARPETA_PUBLICA = "static/pdfs"
RUTA_SECRETO = "settings/.pdf_link_secret"


def _secreto_local(base_dir: Path) -> bytes:
    path = base_dir / RUTA_SECRETO
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("El secreto de enlaces PDF no puede ser un symlink.")
    if not path.exists():
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            pass  # Otra sesión creó el secreto simultáneamente.
        else:
            with os.fdopen(descriptor, "wb") as archivo:
                archivo.write(secrets.token_bytes(32))
    if path.is_symlink():
        raise ValueError("El secreto de enlaces PDF no puede ser un symlink.")
    secret = path.read_bytes()
    if len(secret) != 32:
        raise ValueError("El secreto de enlaces PDF no es válido.")
    return secret


def publicar_pdf(original: Path, base_dir: Path) -> str:
    """Devuelve la URL relativa para LinkColumn sin publicar archivos ajenos.

    Solo acepta archivos bajo uploads/ del proyecto. Un hash HMAC con secreto
    local impide adivinar rutas y da un enlace estable entre sesiones para el
    mismo PDF. El archivo publicado es un hard link del original, si es posible.
    """
    base_dir = base_dir.resolve()
    uploads = (base_dir / "uploads").resolve()
    original = Path(original)
    if not original.is_file() or original.is_symlink():
        return ""
    try:
        real = original.resolve(strict=True)
        relativo = real.relative_to(uploads)
    except (ValueError, OSError):
        return ""
    if len(relativo.parts) != 2 or real.suffix.lower() != ".pdf":
        return ""
    if not real.is_file():
        return ""

    info = real.stat()
    firma = "\n".join((
        relativo.as_posix(),
        str(info.st_size),
        str(info.st_mtime_ns),
    )).encode("utf-8")
    identificador = hmac.new(_secreto_local(base_dir), firma, hashlib.sha256).hexdigest()[:48]
    nombre = real.name.replace("#", "").replace("%", "").replace("?", "")
    if not nombre:
        return ""
    carpeta = base_dir / CARPETA_PUBLICA / identificador
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / nombre
    if destino.is_symlink():
        raise ValueError("Destino PDF inválido: enlace simbólico.")
    if destino.is_file():
        if os.path.samefile(real, destino):
            return f"app/static/pdfs/{identificador}/{nombre}"
        destino.unlink()

    try:
        # Mismo dispositivo: no aumenta el espacio de datos.
        os.link(real, destino)
    except OSError:
        # Cloud Shell normalmente permite hard links. Para sistemas de
        # archivos distintos, conservamos la apertura usando una copia.
        temporal = carpeta / (nombre + ".tmp")
        try:
            shutil.copyfile(real, temporal)
            os.replace(temporal, destino)
        finally:
            temporal.unlink(missing_ok=True)
    return f"app/static/pdfs/{identificador}/{nombre}"
