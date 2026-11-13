"""Activación local y explícita de actas con ChatGPT OAuth.

No valida la existencia jurídica de una autorización institucional: exige
declaración consciente del operador, vinculada a esta sesión y Cloud Shell.
No almacena ni imprime tokens, nombres de personas ni contenido académico.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid

from chatgpt_oauth_cliente import CONFIG_DIR, _session, estado_chatgpt_oauth

VERSION = 1
ARCHIVO_AUTORIZACION = (
    Path(__file__).resolve().parent / "settings" / "chatgpt_oauth_actas_autorizado.json"
)
HOST_ID_PATH = CONFIG_DIR / "host_id.txt"
FRASE_CONFIRMACION = "CONFIRMO AUTORIZACION INSTITUCIONAL"


def _huella_sesion() -> str:
    """Vincula la decisión local al cliente, la identidad y el host específico."""
    session = _session()
    if HOST_ID_PATH.is_symlink() or not HOST_ID_PATH.is_file():
        raise ValueError("No existe identificador privado del host OAuth.")
    host_id = HOST_ID_PATH.read_text(encoding="utf-8").strip()
    if not host_id or len(host_id) > 160:
        raise ValueError("Identificador del host OAuth inválido.")
    datos = "\0".join(
        (str(Path.home().resolve()), host_id, session["client_id"], session["subject"])
    )
    return hashlib.sha256(datos.encode("utf-8")).hexdigest()


def consultar_activacion_actas() -> dict:
    """Fail closed: faltas, archivos inseguros y cambio de identidad desactivan."""
    def no(mensaje: str) -> dict:
        return {"ok": False, "mensaje": mensaje}

    if not estado_chatgpt_oauth().get("ok"):
        return no("Sesión ChatGPT OAuth local ausente o inválida.")
    try:
        ruta = ARCHIVO_AUTORIZACION
        if ruta.is_symlink() or not ruta.is_file():
            return no("Autorización local de actas no configurada.")
        if os.name != "nt" and ruta.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            return no("Autorización local con permisos demasiado amplios.")
        if ruta.stat().st_size > 4096:
            return no("Archivo de autorización local inválido.")
        obj = json.loads(ruta.read_text(encoding="utf-8"))
        if (not isinstance(obj, dict)
                or obj.get("version") != VERSION
                or obj.get("enabled") is not True
                or obj.get("authorization_confirmed") is not True
                or obj.get("external_processing_understood") is not True
                or obj.get("human_review_required") is not True
                or obj.get("session_fingerprint") != _huella_sesion()):
            return no("Autorización local inválida o asociada a otra sesión.")
        return {"ok": True, "mensaje": "Procesamiento OAuth de actas autorizado localmente."}
    except (OSError, ValueError, UnicodeError, TypeError, KeyError):
        return no("No se pudo comprobar la autorización local de actas.")


def _host_id_si_ausente() -> None:
    if HOST_ID_PATH.is_symlink():
        raise ValueError("El identificador del host no puede ser un enlace simbólico.")
    if HOST_ID_PATH.exists():
        if not HOST_ID_PATH.is_file():
            raise ValueError("Identificador del host inválido.")
        return
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if CONFIG_DIR.is_symlink():
        raise ValueError("Carpeta OAuth insegura.")
    # Crear de forma exclusiva; nunca sobrescribir el host_id ya registrado.
    with HOST_ID_PATH.open("x", encoding="utf-8") as fh:
        fh.write(str(uuid.uuid4()) + "\n")
    HOST_ID_PATH.chmod(0o600)


def habilitar_interactivo() -> bool:
    if not estado_chatgpt_oauth().get("ok"):
        print("BLOQUEADO: autoriza primero ChatGPT OAuth en este Cloud Shell.")
        return False
    _host_id_si_ausente()
    print(
        "\nIMPORTANTE: el PDF se envía a LLMWhisperer para extracción y su texto a "
        "OpenAI mediante ChatGPT OAuth. Es necesario disponer de autorización "
        "institucional para ese tratamiento, verificar la elegibilidad del "
        "despliegue y revisar los AHK antes de ejecutarlos."
    )
    print("Esta confirmación no sustituye el permiso formal de la institución.")
    respuesta = input(
        f"Para habilitar únicamente ESTE Cloud Shell, escribe exactamente "
        f"{FRASE_CONFIRMACION}: "
    ).strip()
    if respuesta != FRASE_CONFIRMACION:
        print("SIN CAMBIOS: los PDFs reales siguen bloqueados.")
        return False
    destino = ARCHIVO_AUTORIZACION
    destino.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destino.is_symlink():
        raise ValueError("No se puede guardar autorización a través de un symlink.")
    payload = {
        "version": VERSION,
        "enabled": True,
        "authorization_confirmed": True,
        "external_processing_understood": True,
        "human_review_required": True,
        "session_fingerprint": _huella_sesion(),
        "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    fd, temporal_nombre = tempfile.mkstemp(prefix=".oauth_actas_", dir=destino.parent)
    temporal = Path(temporal_nombre)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.write("\n")
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)
    print("ACTIVACION_OAUTH_ACTAS_LOCAL: OK (sin cambios en otras cuentas).")
    return True


def deshabilitar() -> None:
    if ARCHIVO_AUTORIZACION.is_symlink():
        raise ValueError("Ruta de autorización insegura.")
    ARCHIVO_AUTORIZACION.unlink(missing_ok=True)
    print("ACTIVACION_OAUTH_ACTAS_LOCAL: DESHABILITADA")


def main() -> int:
    parser = argparse.ArgumentParser(description="Control local de actas ChatGPT OAuth")
    parser.add_argument("accion", choices=["estado", "habilitar", "deshabilitar"])
    args = parser.parse_args()
    if args.accion == "estado":
        estado = consultar_activacion_actas()
        print("HABILITADO" if estado["ok"] else "BLOQUEADO")
        print(estado["mensaje"])
        return 0 if estado["ok"] else 1
    if args.accion == "deshabilitar":
        deshabilitar()
        return 0
    return 0 if habilitar_interactivo() else 1


if __name__ == "__main__":
    raise SystemExit(main())
