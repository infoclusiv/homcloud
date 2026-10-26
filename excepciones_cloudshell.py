"""Cloud Shell local-only overrides (not synchronized)."""
import json
import os
from pathlib import Path

LOCAL_PATH = Path(__file__).resolve().parent / "settings" / "excepciones_cloudshell.json"
TIPOS = ("prompts", "modelo", "timeouts")

def leer_excepciones(path: Path = LOCAL_PATH) -> dict[str, bool]:
    if not path.is_file():
        return {tipo: False for tipo in TIPOS}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("El archivo debe ser un objeto JSON.")
        result = {tipo: data.get(tipo, False) for tipo in TIPOS}
        if not all(type(x) is bool for x in result.values()):
            raise ValueError("Los indicadores deben ser booleanos.")
        return result
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f"Excepciones locales inválidas: {exc}") from exc

def guardar_excepcion(tipo: str, activa: bool, path: Path = LOCAL_PATH) -> dict[str, bool]:
    if tipo not in TIPOS or type(activa) is not bool:
        raise ValueError("Excepción inválida.")
    data = leer_excepciones(path)
    data[tipo] = activa
    path.parent.mkdir(parents=True, exist_ok=True)
    temporal = path.with_suffix(".json.tmp")
    try:
        temporal.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporal, path)
    finally:
        temporal.unlink(missing_ok=True)
    return data

def resolver_valor(tipo: str, globales: dict | None, local: dict, excepciones: dict) -> dict:
    if tipo not in TIPOS:
        raise ValueError("Tipo no permitido.")
    if globales is not None and not excepciones.get(tipo, False):
        return globales.copy()
    return local.copy()
