"""Comandos de OpenCode compatibles con las ramas CLI v1 y v2.

Solo construye argumentos y detecta versiones. No envía prompts, PDFs
ni claves a ningún servicio remoto. Usa subprocesos de consulta --version.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess


def detectar_version_opencode(ejecutable: str) -> int:
    """Obtiene el major real, sin asumir que 'opencode models' implica acceso."""
    try:
        respuesta = subprocess.run(
            [ejecutable, "--version"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"No se pudo consultar la versión de OpenCode: {type(exc).__name__}") from exc
    if respuesta.returncode:
        raise RuntimeError("La consulta de versión de OpenCode terminó con error.")
    encontrado = re.search(r"(?<![\d.])v?(\d+)\.\d+\.\d+\b", respuesta.stdout)
    if not encontrado:
        raise RuntimeError("Formato de versión de OpenCode desconocido.")
    major = int(encontrado.group(1))
    if major not in (1, 2):
        raise RuntimeError(
            f"OpenCode {major} todavía no está validado con homcloud; no se enviaron archivos."
        )
    return major


def crear_comando_opencode(
    ejecutable: str,
    major: int,
    prompt: str,
    modelo: str = "",
    archivo: Path | None = None,
    directorio: Path | None = None,
) -> list[str]:
    """v2 usa --standalone para aislar el worker del servidor compartido.

    La CLI v2 documenta run --standalone, run --model y run --file,
    pero NO garantiza la opción v1 'run --dir'. El cwd lo fija Popen.
    """
    if major == 1:
        cmd = [ejecutable, "--print-logs", "--log-level", "WARN", "run"]
        if directorio:
            cmd.extend(["--dir", str(directorio)])
    elif major == 2:
        cmd = [ejecutable, "run", "--standalone"]
    else:
        raise ValueError("Solo se admiten OpenCode v1 y v2.")
    if modelo and modelo.strip():
        cmd.extend(["--model", modelo.strip()])
    if archivo:
        cmd.extend(["--file", str(archivo)])
    cmd.append(prompt)
    return cmd
