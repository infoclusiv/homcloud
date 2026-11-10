"""Preferencia persistente del motor IA de homcloud.

El archivo propio evita que un modelo global de Firestore o la selección
antigua de OpenCode reemplace el modelo elegido para esta cuenta Cloud Shell.
No almacena API keys ni autorizaciones de documentos; solo el ID del motor.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import tempfile

MODELO_DEEPSEEK_PREDETERMINADO = "openrouter::deepseek/deepseek-v4-flash-0731"
ARCHIVO_MOTOR_PREDETERMINADO = (
    Path(__file__).resolve().parent / "settings" / "motor_ia_preferido.txt"
)
_VALIDO = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_:./+-]{0,199}$")


def modelo_id_valido(valor: str) -> bool:
    """Acepta proveedor/modelo o el modelo vacío elegido en OpenCode."""
    return (
        isinstance(valor, str)
        and (valor == "" or (_VALIDO.fullmatch(valor) is not None
                            and "\x00" not in valor))
    )


def cargar_motor_preferido(path: Path | None = None) -> str:
    """Si no existe preferencia nueva, DeepSeek V4 Flash se abre por defecto."""
    ruta = Path(path) if path is not None else ARCHIVO_MOTOR_PREDETERMINADO
    try:
        if not ruta.is_file() or ruta.is_symlink():
            return MODELO_DEEPSEEK_PREDETERMINADO
        contenido = ruta.read_text(encoding="utf-8").strip()
        if not modelo_id_valido(contenido):
            return MODELO_DEEPSEEK_PREDETERMINADO
        return contenido
    except (OSError, UnicodeError):
        return MODELO_DEEPSEEK_PREDETERMINADO


def guardar_motor_preferido(modelo: str, path: Path | None = None) -> None:
    """Guarda cualquier selección explícita; conserva incluso OpenCode Default."""
    valor = str(modelo) if isinstance(modelo, str) else None
    if valor is None or not modelo_id_valido(valor):
        raise ValueError("El identificador del motor no es válido.")
    destino = Path(path) if path is not None else ARCHIVO_MOTOR_PREDETERMINADO
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.is_symlink():
        raise ValueError("No se puede guardar una preferencia en un enlace simbólico.")
    temporal = None
    try:
        fd, archivo = tempfile.mkstemp(dir=destino.parent, prefix=".motor_ia_")
        temporal = Path(archivo)
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as salida:
            salida.write(valor + "\n")
        os.replace(temporal, destino)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)


def autorizar_pago_automatico(modelo: str) -> bool:
    """El usuario autorizó la facturación de los modelos que seleccione."""
    return isinstance(modelo, str) and modelo.startswith("openrouter::") and (
        not modelo.endswith(":batch")
    )
