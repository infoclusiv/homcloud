"""Cliente EXPERIMENTAL ChatGPT OAuth para homcloud (Cloud Shell personal).

No inicia sesión por su cuenta, no lee OPENAI_API_KEY y no guarda secretos
en el repositorio. Reutiliza la sesión previamente consentida del PoC
~/.config/homcloud-siwc-poc/oauth_session.json, exclusivamente en el host.

Esta rama es experimental. Antes de usar documentos reales se requiere
validar elegibilidad del despliegue, privacidad y calidad de extracción.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from urllib import error, parse, request

try:
    import fcntl
except ImportError:
    fcntl = None

CONFIG_DIR = Path.home() / ".config" / "homcloud-siwc-poc"
SESSION_PATH = CONFIG_DIR / "oauth_session.json"
LOCK_PATH = CONFIG_DIR / "oauth_session.lock"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES_NECESARIOS = {"chatgpt.tokens.use.direct", "resource.invoke"}
MODELO_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
MAX_TXT_BYTES = 3 * 1024 * 1024
MAX_RESPUESTA_CHARS = 3 * 1024 * 1024


class ChatGPTOAuthError(RuntimeError):
    """Error sin tokens, contenido académico ni cuerpo HTTP."""


def _session() -> dict:
    if SESSION_PATH.is_symlink() or not SESSION_PATH.is_file():
        raise ChatGPTOAuthError("No se encontró la sesión OAuth privada de este Cloud Shell.")
    if os.name != "nt" and SESSION_PATH.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ChatGPTOAuthError("La sesión OAuth tiene permisos demasiado amplios.")
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise ChatGPTOAuthError("No se pudo leer la sesión OAuth.") from None
    if not isinstance(data, dict) or not data.get("client_id") or not data.get("subject"):
        raise ChatGPTOAuthError("Sesión OAuth incompleta.")
    if not SCOPES_NECESARIOS.issubset(set(data.get("scopes") or [])):
        raise ChatGPTOAuthError("Faltan permisos para usar el plan ChatGPT.")
    return data


def estado_chatgpt_oauth() -> dict:
    """No realiza llamadas remotas ni muestra datos identificadores."""
    try:
        data = _session()
        return {
            "ok": bool(data.get("access_token") and data.get("refresh_token")),
            "token_vigente": time.time() < int(data.get("expires_at") or 0) - 120,
            "mensaje": "Sesión disponible en este Cloud Shell.",
        }
    except (ChatGPTOAuthError, OSError, TypeError, ValueError) as exc:
        return {"ok": False, "token_vigente": False, "mensaje": str(exc)}


def _write_session(data: dict) -> None:
    if SESSION_PATH.is_symlink():
        raise ChatGPTOAuthError("No se puede reemplazar una sesión mediante symlink.")
    if not CONFIG_DIR.is_dir() or CONFIG_DIR.is_symlink():
        raise ChatGPTOAuthError("Directorio de credenciales inválido.")
    fd, name = tempfile.mkstemp(prefix=".oauth_", dir=str(CONFIG_DIR))
    p = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False)
        os.replace(p, SESSION_PATH)
    finally:
        p.unlink(missing_ok=True)


def _token_acceso() -> str:
    """Refresh entre procesos con flock; la lectura se hace dentro del lock."""
    if fcntl is None:
        raise ChatGPTOAuthError("La renovación entre procesos requiere Linux/Cloud Shell.")
    if LOCK_PATH.is_symlink() or CONFIG_DIR.is_symlink():
        raise ChatGPTOAuthError("Ruta OAuth insegura.")
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            data = _session()
            if (data.get("access_token")
                    and time.time() < int(data.get("expires_at") or 0) - 120):
                return data["access_token"]
            earliest = data.get("earliest_refresh_at")
            if isinstance(earliest, (int, float)) and time.time() < earliest:
                raise ChatGPTOAuthError("El servidor todavía no permite renovar la sesión.")
            if not data.get("refresh_token"):
                raise ChatGPTOAuthError("Falta refresh token; reautoriza desde Windows.")
            form = {
                "grant_type": "refresh_token", "client_id": data["client_id"],
                "refresh_token": data["refresh_token"], "resource": RESOURCE,
            }
            req = request.Request(
                TOKEN_URL, data=parse.urlencode(form).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                with request.urlopen(req, timeout=30) as resp:
                    renewed = json.load(resp)
            except error.HTTPError as exc:
                raise ChatGPTOAuthError(f"Renovación OAuth rechazada (HTTP {exc.code}).") from None
            except (error.URLError, TimeoutError):
                raise ChatGPTOAuthError("No se pudo conectar para renovar OAuth.") from None
            if not isinstance(renewed, dict) or not all(
                    renewed.get(k) for k in ("access_token", "refresh_token")):
                raise ChatGPTOAuthError("La renovación no entregó nuevos tokens completos.")
            updated = dict(data)
            updated["access_token"] = renewed["access_token"]
            updated["refresh_token"] = renewed["refresh_token"]
            updated["expires_at"] = int(time.time()) + int(renewed.get("expires_in") or 3600)
            if renewed.get("scope"):
                updated["scopes"] = str(renewed["scope"]).split()
            if "earliest_refresh_at" in renewed:
                updated["earliest_refresh_at"] = renewed["earliest_refresh_at"]
            else:
                updated.pop("earliest_refresh_at", None)
            if not SCOPES_NECESARIOS.issubset(set(updated.get("scopes") or [])):
                raise ChatGPTOAuthError("El permiso OAuth fue revocado; no se guardaron tokens.")
            _write_session(updated)
            return updated["access_token"]
    except OSError:
        raise ChatGPTOAuthError("No se pudo adquirir el bloqueo OAuth.") from None


def listar_modelos_chatgpt_oauth() -> dict:
    """Catálogo actual de la cuenta, sin claves ni perfiles en la respuesta."""
    try:
        req = request.Request(
            RESOURCE + "/models",
            headers={"Authorization": "Bearer " + _token_acceso(), "Accept": "application/json"},
        )
        with request.urlopen(req, timeout=20) as resp:
            content = resp.read(2_000_001)
        if len(content) > 2_000_000:
            raise ChatGPTOAuthError("Catálogo OAuth demasiado grande.")
        data = json.loads(content)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ChatGPTOAuthError("Formato de catálogo OAuth no reconocido.")
        models = [
            {"id": x["slug"], "name": str(x.get("display_name") or x["slug"])}
            for x in data["models"]
            if isinstance(x, dict) and x.get("visibility") == "list"
            and isinstance(x.get("slug"), str) and MODELO_RE.fullmatch(x["slug"])
        ]
        return {"ok": True, "models": [x["id"] for x in models], "details": models}
    except error.HTTPError as exc:
        return {"ok": False, "models": [], "error": f"Catálogo OAuth HTTP {exc.code}."}
    except (error.URLError, TimeoutError, OSError, ValueError, TypeError, ChatGPTOAuthError):
        return {"ok": False, "models": [], "error": "No se pudo consultar el catálogo ChatGPT OAuth."}


def _sse_events(stream):
    parts = []
    for raw_line in stream:
        line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("data:"):
            parts.append(line[5:].lstrip())
        elif not line and parts:
            raw = "\n".join(parts)
            parts.clear()
            if raw != "[DONE]":
                try:
                    ev = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(ev, dict):
                    yield ev
    if parts:
        try:
            ev = json.loads("\n".join(parts))
            if isinstance(ev, dict):
                yield ev
        except (ValueError, TypeError):
            pass


def _read_events(events, cancelar=None) -> str:
    output, count, completed = [], 0, False
    for ev in events:
        if cancelar is not None and cancelar.is_set():
            raise ChatGPTOAuthError("La inferencia se canceló por timeout del lote.")
        kind = ev.get("type")
        if kind == "response.output_text.delta":
            part = ev.get("delta")
            if isinstance(part, str):
                count += len(part)
                if count > MAX_RESPUESTA_CHARS:
                    raise ChatGPTOAuthError("Salida de IA excesiva; respuesta descartada.")
                output.append(part)
        elif kind in ("response.failed", "response.incomplete", "error"):
            code = ((ev.get("response") or {}).get("error") or {})
            name = str(code.get("code", "rechazado")) if isinstance(code, dict) else "rechazado"
            name = re.sub(r"[^a-zA-Z0-9_.-]", "", name)[:60]
            raise ChatGPTOAuthError("La inferencia terminó con error: " + name)
        elif kind == "response.completed":
            completed = True
    if not completed:
        raise ChatGPTOAuthError("La conexión terminó sin response.completed.")
    answer = "".join(output).strip()
    if not answer:
        raise ChatGPTOAuthError("El modelo no devolvió texto.")
    return answer


def ejecutar_chatgpt_oauth(
    *, prompt: str, txt_path: Path, modelo: str, timeout_segundos: int = 120,
    cancelar=None,
) -> dict:
    """Misma forma de resultado que OpenCode/OpenRouter. No adjunta PDF."""
    start = time.monotonic()
    def fallo(msg: str) -> dict:
        return {
            "ok": False, "stdout": "", "stderr": "", "error": msg, "returncode": 1,
            "timeout": "timeout" in msg.lower(), "duracion_segundos": round(time.monotonic()-start, 2),
            "diagnostico": {"clasificacion": "Error ChatGPT OAuth"},
        }
    if not isinstance(modelo, str) or not MODELO_RE.fullmatch(modelo):
        return fallo("Modelo ChatGPT OAuth inválido.")
    if cancelar is not None and cancelar.is_set():
        return fallo("Cancelado antes de enviar el TXT.")
    try:
        file = Path(txt_path)
        if not file.is_file() or file.is_symlink() or file.stat().st_size > MAX_TXT_BYTES:
            raise ChatGPTOAuthError("El TXT no existe o supera el tamaño autorizado.")
        text = file.read_text(encoding="utf-8")
        if not text.strip():
            raise ChatGPTOAuthError("El TXT está vacío.")
        data = {
            "model": modelo,
            "instructions": prompt,
            "input": [{"role": "user", "content": "TEXTO EXTRAÍDO POR LLMWHISPERER:\n\n" + text}],
            "store": False,
            "stream": True,
        }
        req = request.Request(
            RESOURCE + "/responses", method="POST",
            data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + _token_acceso(),
                "Content-Type": "application/json", "Accept": "text/event-stream",
            },
        )
        with request.urlopen(req, timeout=max(10, min(300, int(timeout_segundos)))) as resp:
            answer = _read_events(_sse_events(resp), cancelar=cancelar)
        return {
            "ok": True, "stdout": answer, "stderr": "", "error": "",
            "returncode": 0, "timeout": False,
            "duracion_segundos": round(time.monotonic()-start, 2),
        }
    except error.HTTPError as exc:
        return fallo(f"Responses API rechazó la solicitud (HTTP {exc.code}).")
    except (error.URLError, TimeoutError):
        return fallo("Error de red o timeout con ChatGPT OAuth.")
    except (ChatGPTOAuthError, OSError, UnicodeError, ValueError) as exc:
        return fallo(str(exc))
