#!/usr/bin/env bash
# Inicia homcloud en la vista previa de Google Cloud Shell.
# Compatible con distintas cuentas de Cloud Shell sin URLs ni usuarios fijos.
set -Eeuo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
BASE_DIR="$(pwd -P)"
PORT="${HOMCLOUD_PORT:-8501}"

if [[ -z "${WEB_HOST:-}" ]]; then
  echo "Error: WEB_HOST no esta disponible. Este iniciador es solo para Google Cloud Shell." >&2
  echo "No se desactivaran las protecciones CORS/XSRF fuera de Cloud Shell." >&2
  exit 1
fi

if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( 10#$PORT < 2000 || 10#$PORT > 65000 )); then
  echo "Error: HOMCLOUD_PORT debe estar entre 2000 y 65000." >&2
  exit 1
fi

if [[ -x ".venv/bin/python" ]]; then
  PYTHON="$BASE_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "Error: crea el entorno virtual .venv e instala Streamlit." >&2
  exit 1
fi

if ! "$PYTHON" -c 'import streamlit' >/dev/null 2>&1; then
  echo "Error: Streamlit no esta instalado en $PYTHON." >&2
  echo "Instala las dependencias en el entorno virtual de esta cuenta." >&2
  exit 1
fi

# Detener solamente una instancia anterior de homcloud, no otras aplicaciones.
if command -v fuser >/dev/null 2>&1; then
  PIDS="$(fuser -n tcp "$PORT" 2>/dev/null || true)"
  for PID in $PIDS; do
    [[ "$PID" =~ ^[0-9]+$ ]] || continue
    CMD="$(tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null || true)"
    CWD="$(readlink -f "/proc/$PID/cwd" 2>/dev/null || true)"
    if [[ "$CWD" != "$BASE_DIR" || "$CMD" != *streamlit* || "$CMD" != *app.py* ]]; then
      echo "Error: el puerto $PORT esta ocupado por otra aplicacion (PID $PID)." >&2
      echo "No se ha detenido ese proceso." >&2
      exit 1
    fi
  done
  for PID in $PIDS; do
    [[ "$PID" =~ ^[0-9]+$ ]] || continue
    echo "Cerrando homcloud anterior (PID $PID)..."
    kill -TERM "$PID" 2>/dev/null || true
  done
  if [[ -n "$PIDS" ]]; then
    for _ in 1 2 3 4 5; do
      if ! fuser -n tcp "$PORT" >/dev/null 2>&1; then break; fi
      sleep 1
    done
    if fuser -n tcp "$PORT" >/dev/null 2>&1; then
      echo "Error: el puerto $PORT sigue ocupado. Revisa el proceso antes de continuar." >&2
      exit 1
    fi
  fi
else
  echo "Aviso: fuser no esta disponible; no se cerrara una instancia anterior." >&2
fi

echo "Iniciando homcloud en la cuenta de Cloud Shell actual..."
echo "URL de esta cuenta: https://${PORT}-${WEB_HOST}"
echo "Selecciona Web Preview > Preview on port $PORT."
echo "Para detener la aplicacion, presiona Ctrl+C."

# Parametros recomendados por Google para Streamlit tras su proxy HTTPS.
# No se guardan en config.toml: solo aplican a esta ejecucion de Cloud Shell.
exec "$PYTHON" -m streamlit run app.py \
  --server.address=0.0.0.0 \
  --server.port="$PORT" \
  --server.headless=true \
  --browser.serverAddress=localhost \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false
