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

# Preferencia independiente del modelo/otras APIs. "auto" omite el campo
# reasoning: mantiene el comportamiento ya validado de la PoC.
RAZONAMIENTO_CHATGPT_OAUTH_PREDETERMINADO = "auto"
RAZONAMIENTOS_CHATGPT_OAUTH = ("auto", "low", "medium", "high", "xhigh", "max")
ARCHIVO_RAZONAMIENTO_CHATGPT_OAUTH = (
    Path(__file__).resolve().parent / "settings" / "razonamiento_chatgpt_oauth.txt"
)


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


def cargar_razonamiento_chatgpt_oauth(path: Path | None = None) -> str:
    """Devuelve el esfuerzo OAuth guardado; ante falta/corrupción usa auto."""
    ruta = Path(path) if path is not None else ARCHIVO_RAZONAMIENTO_CHATGPT_OAUTH
    try:
        if not ruta.is_file() or ruta.is_symlink():
            return RAZONAMIENTO_CHATGPT_OAUTH_PREDETERMINADO
        nivel = ruta.read_text(encoding="utf-8").strip()
        if nivel in RAZONAMIENTOS_CHATGPT_OAUTH:
            return nivel
    except (OSError, UnicodeError):
        pass
    return RAZONAMIENTO_CHATGPT_OAUTH_PREDETERMINADO


def guardar_razonamiento_chatgpt_oauth(nivel: str, path: Path | None = None) -> None:
    """Guarda localmente en 0600, de forma atómica y fuera de Git."""
    if not isinstance(nivel, str) or nivel not in RAZONAMIENTOS_CHATGPT_OAUTH:
        raise ValueError("Nivel de razonamiento ChatGPT OAuth inválido.")
    destino = Path(path) if path is not None else ARCHIVO_RAZONAMIENTO_CHATGPT_OAUTH
    guardar_motor_preferido(nivel, destino)


def autorizar_pago_automatico(modelo: str) -> bool:
    """El usuario autorizó la facturación de los modelos que seleccione."""
    return isinstance(modelo, str) and modelo.startswith("openrouter::") and (
        not modelo.endswith(":batch")
    )
