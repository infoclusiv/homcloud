"""Diagnóstico de OpenCode sin bloquear el lote ni registrar prompts en metadatos.

La salida original y stderr (potencialmente privados) se guardan únicamente
en outputs/runs/<lote>/_workers/... durante la retención de los lotes.
El JSON resumido contiene solo estados, tiempos, tamaños y códigos detectados.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
from collections import Counter, deque
from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

FRECUENCIA_SEGUNDOS = 2.0
LIMITE_STDOUT = 8 * 1024 * 1024
LIMITE_STDERR = 3 * 1024 * 1024
NOMBRE_ESTADO = "opencode_diagnostico.json"
NOMBRE_STDOUT = "opencode_stdout.log"
NOMBRE_STDERR = "opencode_stderr.log"
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{6,80}$")


def clasificar_error(stderr: str) -> str:
    """Categoría informativa, sin publicar el cuerpo del mensaje."""
    s = stderr.casefold()
    patrones = (
        ("HTTP 429 / cuota o rate limit", r"(?:\b429\b|ratelimit|rate.limit|too many requests|quota.exceeded|free.?tier.?limit)"),
        ("HTTP 401 / autenticación", r"(?:\b401\b|unauthorized|authentication failed|invalid.api.key)"),
        ("HTTP 403 / acceso restringido", r"(?:\b403\b|forbidden|permission denied|not allowed)"),
        ("HTTP 402 / saldo o facturación", r"(?:\b402\b|insufficient.credits|payment required)"),
        ("HTTP 5xx / proveedor no disponible", r"(?:\b50[0234]\b|bad gateway|service unavailable|internal server error)"),
        ("Modelo no disponible", r"(?:providermodelnotfound|model not found|model is not available|unknown model)"),
        ("Conexión / DNS / TLS", r"(?:econnreset|enotfound|eai_again|etimedout|tls|certificate|network error|connection refused)"),
        ("Límite de contexto / tokens", r"(?:context.length|context window|too many tokens|maximum tokens)"),
        ("Timeout remoto", r"(?:request timed out|upstream timeout|fetch failed|timeout.*request)"),
    )
    for nombre, patron in patrones:
        if re.search(patron, s):
            return nombre
    return "Sin error reconocible en stderr" if s.strip() else "Sin mensajes en stderr"


def _cola(path: Path, max_bytes: int = 65536) -> str:
    try:
        with path.open("rb") as archivo:
            archivo.seek(0, os.SEEK_END)
            size = archivo.tell()
            archivo.seek(max(0, size - max_bytes))
            return archivo.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _tamano(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _guardar_estado(path: Path, datos: dict) -> None:
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _terminar_grupo(proceso: subprocess.Popen) -> None:
    if proceso.poll() is not None:
        return
    if os.name == "nt":
        proceso.terminate()
    else:
        try:
            os.killpg(proceso.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            proceso.terminate()
    try:
        proceso.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proceso.kill()
        else:
            try:
                os.killpg(proceso.pid, signal.SIGKILL)
            except OSError:
                proceso.kill()
        try:
            proceso.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def ejecutar_monitoreado(
    comando: list[str],
    cwd: Path,
    timeout_segundos: int,
    cancelar: threading.Event | None = None,
    identificador_modelo: str = "",
    limite_stdout: int = LIMITE_STDOUT,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Escribe diagnósticos mientras la CLI está activa y termina hijos al cancelar.

    No hay pipes stdout/stderr que puedan bloquearse por falta de lectura.
    Los logs no se incluyen en el CSV y se eliminan con los temporales del lote.
    """
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    diagnostico = cwd.parent
    diagnostico.mkdir(parents=True, exist_ok=True)
    estado_path = diagnostico / NOMBRE_ESTADO
    stdout_path = diagnostico / NOMBRE_STDOUT
    stderr_path = diagnostico / NOMBRE_STDERR
    inicio = time.monotonic()
    estado = {
        "estado": "iniciando", "modelo": identificador_modelo[:200],
        "inicio_utc": datetime.now(timezone.utc).isoformat(),
        "transcurridos_segundos": 0, "pid": None,
        "stdout_bytes": 0, "stderr_bytes": 0,
        "segundos_sin_salida": 0, "clasificacion": "Sin mensajes en stderr",
        "codigo_salida": None, "timeout_segundos": timeout_segundos,
        "terminacion": None,
    }
    proceso = None
    anterior_out = anterior_err = 0
    ultima_salida = inicio
    ultima_escritura = 0.0

    def informar() -> None:
        # Nunca se comparten stdout, stderr, comandos, prompts ni tokens.
        if on_progress:
            try:
                on_progress(dict(estado))
            except Exception:
                pass  # Una visualización no debe interrumpir el procesamiento.

    try:
        kwargs = {"cwd": str(cwd), "start_new_session": os.name != "nt"}
        if os.name == "nt":
            kwargs.pop("start_new_session")
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        with stdout_path.open("wb") as salida, stderr_path.open("wb") as error:
            os.chmod(stdout_path, 0o600)
            os.chmod(stderr_path, 0o600)
            _guardar_estado(estado_path, estado)
            proceso = subprocess.Popen(comando, stdout=salida, stderr=error, stdin=subprocess.DEVNULL, **kwargs)
            estado["pid"] = proceso.pid
            informar()
            while True:
                ahora = time.monotonic()
                out_size, err_size = _tamano(stdout_path), _tamano(stderr_path)
                if out_size != anterior_out or err_size != anterior_err:
                    ultima_salida = ahora
                    anterior_out, anterior_err = out_size, err_size
                estado.update({
                    "transcurridos_segundos": round(ahora - inicio, 1),
                    "stdout_bytes": out_size,
                    "stderr_bytes": err_size,
                    "segundos_sin_salida": round(ahora - ultima_salida, 1),
                    "clasificacion": clasificar_error(_cola(stderr_path)),
                })
                motivo = None
                if cancelar is not None and cancelar.is_set():
                    motivo = "cancelado_por_timeout_del_lote"
                elif ahora - inicio >= timeout_segundos:
                    motivo = "timeout_opencode"
                elif out_size > limite_stdout:
                    motivo = "stdout_excesivo_posible_bucle"
                elif err_size > LIMITE_STDERR:
                    motivo = "stderr_excesivo"
                if motivo:
                    estado["terminacion"] = motivo
                    _guardar_estado(estado_path, {**estado, "estado": "cancelando"})
                    informar()
                    _terminar_grupo(proceso)
                    break
                if proceso.poll() is not None:
                    break
                if ahora - ultima_escritura >= 5:
                    estado["estado"] = "en_ejecucion"
                    _guardar_estado(estado_path, estado)
                    informar()
                    ultima_escritura = ahora
                time.sleep(FRECUENCIA_SEGUNDOS)
            try:
                proceso.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _terminar_grupo(proceso)
        codigo = proceso.poll() if proceso else None
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        estado.update({
            "estado": "completado" if codigo == 0 and not estado["terminacion"] else "error",
            "codigo_salida": codigo,
            "transcurridos_segundos": round(time.monotonic() - inicio, 1),
            "stdout_bytes": len(stdout.encode("utf-8")),
            "stderr_bytes": len(stderr.encode("utf-8")),
            "clasificacion": clasificar_error(stderr[-65536:]),
        })
        _guardar_estado(estado_path, estado)
        informar()
        motivo = estado["terminacion"]
        return {
            "ok": codigo == 0 and not motivo, "returncode": codigo,
            "stdout": stdout, "stderr": stderr,
            "timeout": motivo in {"timeout_opencode", "cancelado_por_timeout_del_lote"},
            "cancelado_por_lote": motivo == "cancelado_por_timeout_del_lote",
            "error": motivo or ("" if codigo == 0 else "OpenCode finalizó con error."),
            "duracion_segundos": estado["transcurridos_segundos"],
            "timeout_segundos": timeout_segundos,
            "diagnostico": estado,
            "diagnostico_path": str(estado_path),
            "cwd": str(cwd),
        }
    except KeyboardInterrupt:
        # Ctrl+C no hereda de Exception: antes dejaba el subproceso vivo.
        # Capturarlo aquí permite cerrar OpenCode y devolver un diagnóstico
        # seguro en vez de un traceback y un proceso potencialmente huérfano.
        if proceso is not None:
            _terminar_grupo(proceso)
        estado.update({
            "estado": "interrumpido",
            "terminacion": "interrumpido_por_usuario",
            "codigo_salida": proceso.poll() if proceso is not None else None,
            "transcurridos_segundos": round(time.monotonic() - inicio, 1),
            "stdout_bytes": _tamano(stdout_path),
            "stderr_bytes": _tamano(stderr_path),
            "clasificacion": clasificar_error(_cola(stderr_path)),
        })
        _guardar_estado(estado_path, estado)
        informar()
        return {
            "ok": False, "error": "Prueba interrumpida con Ctrl+C; OpenCode detenido.",
            "stdout": "", "stderr": "", "returncode": estado["codigo_salida"],
            "timeout": False, "cancelado_por_lote": False,
            "duracion_segundos": estado["transcurridos_segundos"],
            "timeout_segundos": timeout_segundos,
            "diagnostico": estado, "diagnostico_path": str(estado_path),
            "cwd": str(cwd),
        }
    except Exception as exc:
        if proceso is not None:
            _terminar_grupo(proceso)
        estado.update({"estado": "error_ejecucion", "terminacion": type(exc).__name__})
        _guardar_estado(estado_path, estado)
        return {
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
            "stdout": "", "stderr": "", "timeout": False,
            "diagnostico": estado, "diagnostico_path": str(estado_path),
            "cwd": str(cwd),
        }


def resumir_lote(base_dir: Path, run_id: str) -> list[dict]:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Identificador de lote inválido.")
    runs = (Path(base_dir) / "outputs" / "runs").resolve()
    workers = runs / run_id / "_workers"
    if not workers.is_dir() or workers.is_symlink():
        return []
    filas = []
    for path in sorted(workers.glob("*/" + NOMBRE_ESTADO)):
        if path.is_symlink() or not path.resolve().is_relative_to(workers.resolve()):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            filas.append({
                "Worker": path.parent.name,
                "Modelo": data.get("modelo"),
                "Estado OpenCode": data.get("estado"),
                "Causa detectada": data.get("clasificacion"),
                "Terminación": data.get("terminacion"),
                "Segundos": data.get("transcurridos_segundos"),
                "Sin salida (s)": data.get("segundos_sin_salida"),
                "Salida (bytes)": data.get("stdout_bytes"),
                "Errores (bytes)": data.get("stderr_bytes"),
                "Código salida": data.get("codigo_salida"),
            })
        except (OSError, ValueError):
            continue
    return filas


def resumir_logs_existentes(horas: int = 48, carpeta: Path | None = None) -> dict:
    """Resume posibles errores del log general de OpenCode sin imprimir datos.

    Puede servir para lotes anteriores a la instalación del monitoreo.
    Los avisos son indicios, NO una asociación probada con un lote concreto.
    """
    if type(horas) is not int or not 1 <= horas <= 168:
        raise ValueError("El período debe estar entre 1 y 168 horas.")
    directorio = carpeta or (Path.home() / ".local" / "share" / "opencode" / "log")
    archivos = sorted(directorio.glob("*.log")) if directorio.is_dir() else (
        [directorio] if directorio.is_file() else []
    )
    umbral = time.time() - horas * 3600
    categorias = Counter()
    revisados = 0
    for archivo in archivos[-20:]:
        try:
            if archivo.is_symlink() or archivo.stat().st_mtime < umbral:
                continue
            revisados += 1
            with archivo.open("r", encoding="utf-8", errors="replace") as f:
                for linea in deque(f, maxlen=20000):
                    clase = clasificar_error(linea)
                    if clase not in ("Sin mensajes en stderr", "Sin error reconocible en stderr"):
                        categorias[clase] += 1
        except OSError:
            continue
    return {
        "archivos_revisados": revisados,
        "horas": horas,
        "indicadores": dict(categorias.most_common()),
        "nota": "Conteos orientativos; el log podría contener eventos de otros lotes.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico OpenCode sin mostrar textos privados")
    sub = parser.add_subparsers(dest="accion", required=True)
    lote = sub.add_parser("lote")
    lote.add_argument("run_id")
    prueba = sub.add_parser("probar")
    prueba.add_argument("--model", required=True)
    prueba.add_argument("--timeout", type=int, default=45)
    logs = sub.add_parser("logs")
    logs.add_argument("--horas", type=int, default=48)
    args = parser.parse_args(argv)
    base = Path(__file__).resolve().parent
    if args.accion == "logs":
        print(json.dumps(resumir_logs_existentes(args.horas), ensure_ascii=False, indent=2))
        return 0
    if args.accion == "lote":
        print(json.dumps(resumir_lote(base, args.run_id), ensure_ascii=False, indent=2))
        return 0
    if not 5 <= args.timeout <= 180:
        parser.error("timeout debe estar entre 5 y 180 segundos")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:/@+-]+", args.model):
        parser.error("identificador del modelo inválido")
    comando = shutil.which("opencode")
    if not comando:
        print("ERROR: no se encontró opencode en PATH", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="homcloud_probe_") as temp:
        root = Path(temp)
        cmd = [
            comando, "--print-logs", "--log-level", "WARN",
            "run", "--model", args.model,
            "Responde únicamente con la palabra OK.",
        ]
        print(
            f"Probando {args.model} con límite de {args.timeout}s. "
            "Mostraré el estado cada 5 segundos. "
            "Ctrl+C finalizará la prueba y detendrá OpenCode.",
            flush=True,
        )

        def progreso(estado: dict) -> None:
            transcurrido = estado.get("transcurridos_segundos", 0)
            clasificacion = estado.get("clasificacion") or "Sin clasificación"
            print(
                f"[{transcurrido:>5}s/{args.timeout}s] "
                f"estado={estado.get('estado')} "
                f"stdout={estado.get('stdout_bytes', 0)} B "
                f"stderr={estado.get('stderr_bytes', 0)} B "
                f"sin_salida={estado.get('segundos_sin_salida', 0)} s "
                f"señal={clasificacion}",
                flush=True,
            )

        resultado = ejecutar_monitoreado(
            cmd, root / "opencode_cwd", args.timeout,
            identificador_modelo=args.model,
            on_progress=progreso,
        )
        diag = resultado.get("diagnostico") or {}
        respondio = resultado["ok"] and "OK" in (resultado.get("stdout") or "").upper()
        print(json.dumps({
            "ok": bool(respondio),
            "proceso_sin_error": resultado["ok"],
            "respondio_prueba": bool(respondio),
            "codigo_salida": resultado.get("returncode"),
            "duracion_segundos": resultado.get("duracion_segundos"),
            "clasificacion": diag.get("clasificacion"),
            "terminacion": diag.get("terminacion"),
            "stdout_bytes": diag.get("stdout_bytes"),
            "stderr_bytes": diag.get("stderr_bytes"),
        }, ensure_ascii=False, indent=2))
        if diag.get("terminacion") == "interrumpido_por_usuario":
            print("Se canceló la prueba; el proceso de OpenCode fue detenido.", flush=True)
            return 130
        return 0 if respondio else 1


if __name__ == "__main__":
    raise SystemExit(main())
