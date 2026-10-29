"""Historial compacto de homologaciones y retención automática de lotes.

Persistencia: Firestore compartido (si está configurado), con CSV local como
copia auxiliar; sin Firestore, solo CSV local. Jamás se elimina un lote antiguo
si no se confirmó primero la conservación de sus registros.

El mantenimiento se ejecuta al iniciar la app y después de cada lote. Cloud
Shell apagado NO ejecuta tareas programadas; al volver a abrir se regulariza.
"""
from __future__ import annotations

import csv
import fcntl
from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import time

from programas_planes_sync import ErrorSincronizacion, proyecto_configurado

RETENCION_DIAS_DEFAULT = 3
CARPETA_HISTORIAL = "historial"
NOMBRE_CSV = "homologaciones_historico.csv"
REGISTROS_COLECCION = "homcloud_historial_registros"
MARCA_ACTIVO = ".procesamiento_activo"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,80}$")
COLUMNAS = (
    "ID registro", "Fecha", "Cloud Shell", "Lote", "Lote padre",
    "Archivo", "Nivel", "Prompt usado", "Programa origen",
    "Programa al que aspira", "Plan", "Créditos homologados",
    "Estado", "Error", "Duración", "Modelo OpenCode",
)


def validar_dias(dias: int) -> int:
    if type(dias) is not int or not 1 <= dias <= 90:
        raise ValueError("Los días de retención deben estar entre 1 y 90.")
    return dias


def _run_dir(base: Path, run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("ID de lote inválido.")
    return base / "outputs" / "runs" / run_id


def _leer_csv(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _metadatos(ruta: Path) -> dict:
    path = ruta / "metadata_lote.json"
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (ValueError, UnicodeError, OSError):
        return {}


def _fecha_lote(run_id: str, ruta: Path) -> datetime:
    # Usar la fecha de creación en el identificador, NO la mtime que cambia
    # al escribir un CSV o descargar resultados.
    try:
        return datetime.strptime(run_id[:15], "%Y%m%d_%H%M%S")
    except (ValueError, TypeError):
        return datetime.fromtimestamp(ruta.stat().st_mtime)


def lote_en_ejecucion(ruta: Path) -> bool:
    marca = ruta / MARCA_ACTIVO
    if not marca.is_file():
        return False
    try:
        pid = int(marca.read_text(encoding="ascii").strip())
        if pid <= 0:
            return False
        # Cuando hay /proc, verificar que el PID todavía sea el servidor
        # Streamlit asociado a la aplicación para evitar PIDs reutilizados.
        cmdline = Path(f"/proc/{pid}/cmdline")
        if cmdline.exists():
            texto = cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
            return "streamlit" in texto and "app.py" in texto
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _filas_lote(base: Path, ruta: Path) -> tuple[list[dict], str]:
    final = ruta / "resumen_resultados.csv"
    parcial = ruta / "resumen_resultados_parcial.csv"
    csv_elegido = final if final.is_file() else parcial
    filas = _leer_csv(csv_elegido)
    # Solo filas propias de este intento. El CSV combinado del reintento
    # conserva la base, así que no hay que duplicarla en el histórico.
    metadata = _metadatos(ruta)
    if metadata.get("parent_run_id") and (ruta / "metadata_resultado_combinado.json").is_file():
        # El CSV del reintento puede incluir todas las filas del lote padre.
        # En el histórico se guardan solamente los PDFs REALMENTE reintentados,
        # usando los archivos de uploads del propio intento.
        uploads_reintento = base / "uploads" / ruta.name
        if uploads_reintento.is_dir() and not uploads_reintento.is_symlink():
            nombres_reintentados = {
                f.name.casefold() for f in uploads_reintento.iterdir()
                if f.is_file() and not f.is_symlink() and f.suffix.lower() == ".pdf"
            }
            if nombres_reintentados:
                filas = [
                    f for f in filas
                    if str(f.get("Archivo") or "").casefold() in nombres_reintentados
                ]

    encontrados = {str(f.get("Archivo") or "").casefold() for f in filas}
    uploads = base / "uploads" / ruta.name
    if uploads.is_dir() and not uploads.is_symlink():
        for pdf in sorted(uploads.iterdir()):
            if pdf.is_file() and not pdf.is_symlink() and pdf.suffix.lower() == ".pdf":
                if pdf.name.casefold() not in encontrados:
                    filas.append({
                        "Archivo": pdf.name,
                        "Estado": "Error no iniciado",
                        "Error": "El lote terminó sin generar un resultado para este PDF.",
                    })
                    encontrados.add(pdf.name.casefold())
    huella = hashlib.sha256()
    for f in filas:
        huella.update(json.dumps(f, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        huella.update(b"\n")
    return filas, huella.hexdigest()


def registros_de_lote(base: Path, run_id: str) -> tuple[list[dict], str]:
    ruta = _run_dir(base, run_id)
    if not ruta.is_dir() or ruta.is_symlink():
        raise FileNotFoundError(run_id)
    filas, huella = _filas_lote(base, ruta)
    metadata = _metadatos(ruta)
    fecha = metadata.get("fecha") or _fecha_lote(run_id, ruta).isoformat(timespec="seconds")
    cuenta = os.environ.get("USER") or os.environ.get("LOGNAME") or socket.gethostname()
    registros = []
    for indice, fila in enumerate(filas):
        nombre = str(fila.get("Archivo") or "")
        identificador_archivo = hashlib.sha256(
            nombre.casefold().encode("utf-8")
        ).hexdigest()[:24] if nombre else f"fila{indice:05d}"
        # ID estable por lote+archivo: reescribir un reintento corregido
        # no duplica registros históricos ni depende del orden del CSV.
        ident = f"{run_id}_{identificador_archivo}"
        registros.append({
            "ID registro": ident,
            "Fecha": str(fecha),
            "Cloud Shell": str(cuenta),
            "Lote": run_id,
            "Lote padre": str(metadata.get("parent_run_id") or ""),
            "Archivo": nombre[:350],
            "Nivel": str(fila.get("Nivel") or "")[:500],
            "Prompt usado": str(fila.get("Prompt usado") or "")[:500],
            "Programa origen": str(fila.get("Programa origen") or "")[:500],
            "Programa al que aspira": str(fila.get("Programa al que aspira") or "")[:500],
            "Plan": str(fila.get("Plan") or "")[:500],
            "Créditos homologados": str(fila.get("Créditos homologados") or "")[:500],
            "Estado": str(fila.get("Estado") or "")[:500],
            "Error": str(fila.get("Error") or "")[:1500],
            "Duración": str(fila.get("Duración") or "")[:500],
            "Modelo OpenCode": str(fila.get("Modelo OpenCode") or metadata.get("modelo_opencode") or "")[:200],
        })
    return registros, huella


def _guardar_csv_local(base: Path, registros: list[dict]) -> None:
    """CSV acumulativo, atómico, privado e idempotente, con bloqueo local."""
    path = base / CARPETA_HISTORIAL / NOMBRE_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    cerrojo = path.parent / ".csv_historial.lock"
    with cerrojo.open("a+") as lock:
        os.chmod(cerrojo, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            anteriores = {
                f["ID registro"]: f for f in _leer_csv(path)
                if f.get("ID registro")
            }
            anteriores.update({f["ID registro"]: f for f in registros})
            temporal = path.with_suffix(".csv.tmp")
            try:
                with temporal.open("w", encoding="utf-8-sig", newline="") as f:
                    os.chmod(temporal, 0o600)
                    writer = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(
                        sorted(anteriores.values(), key=lambda row: row["ID registro"])
                    )
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporal, path)
            finally:
                temporal.unlink(missing_ok=True)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _subir_firestore(registros: list[dict], proyecto: str) -> None:
    # Una fila por documento: sin límite de 1 MiB de un único CSV.
    # Escrituras idempotentes: reintentar el mismo lote actualiza IDs iguales.
    from google.cloud import firestore
    client = firestore.Client(project=proyecto)
    col = client.collection(REGISTROS_COLECCION)
    for inicio in range(0, len(registros), 200):
        batch = client.batch()
        for registro in registros[inicio:inicio+200]:
            batch.set(col.document(registro["ID registro"]), registro)
        batch.commit()


def archivar_lote(base: Path, run_id: str) -> dict:
    """Confirma copia local y, si existe, Firestore antes de registrar recibo."""
    ruta = _run_dir(base, run_id)
    registros, huella = registros_de_lote(base, run_id)
    if not registros:
        raise ValueError("Sin filas de resultados o PDFs para archivar.")
    recibo = base / CARPETA_HISTORIAL / "recibos" / f"{run_id}.json"
    proyecto = proyecto_configurado()
    if recibo.is_file():
        try:
            datos = json.loads(recibo.read_text(encoding="utf-8"))
            if datos.get("hash") == huella and datos.get("proyecto") == proyecto:
                return {"run_id": run_id, "filas": len(registros), "ya_archivado": True}
        except (ValueError, OSError):
            pass

    # Conservar primero una copia compacta local. Si Firestore está caído,
    # el CSV local sigue disponible, pero NO se autoriza eliminar los PDFs.
    _guardar_csv_local(base, registros)
    if proyecto:
        try:
            _subir_firestore(registros, proyecto)
        except Exception as exc:
            raise ErrorSincronizacion(f"Falló guardar el historial en Firestore: {exc}") from exc
    recibo.parent.mkdir(parents=True, exist_ok=True)
    temporal = recibo.with_suffix(".json.tmp")
    try:
        temporal.write_text(json.dumps({
            "hash": huella, "proyecto": proyecto, "filas": len(registros),
        }, ensure_ascii=False), encoding="utf-8")
        os.replace(temporal, recibo)
    finally:
        temporal.unlink(missing_ok=True)
    return {"run_id": run_id, "filas": len(registros), "ya_archivado": False}


def exportar_historial(base: Path) -> list[dict]:
    """Descarga global cuando hay Firestore; sin proyecto usa CSV local."""
    proyecto = proyecto_configurado()
    if not proyecto:
        return _leer_csv(base / CARPETA_HISTORIAL / NOMBRE_CSV)
    try:
        from google.cloud import firestore
        cliente = firestore.Client(project=proyecto)
        registros = []
        for snap in cliente.collection(REGISTROS_COLECCION).stream(timeout=120):
            registro = snap.to_dict()
            if isinstance(registro, dict) and registro.get("ID registro"):
                registros.append(registro)
        return sorted(registros, key=lambda r: (str(r.get("Fecha") or ""), str(r["ID registro"])))
    except Exception as exc:
        raise ErrorSincronizacion(f"No se pudo descargar el historial global: {exc}") from exc


def csv_historial_bytes(registros: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=COLUMNAS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(registros)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _borrar_path(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"No se eliminan enlaces simbólicos: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()


def limpiar_antiguos(base: Path, dias: int = RETENCION_DIAS_DEFAULT) -> dict:
    """Archiva antes de borrar; lotes activos se conservan siempre.

    Los PDFs publicados mediante hardlinks tienen carpeta propia en static/pdfs,
    así que limpiamos también publicaciones antiguas.
    """
    dias = validar_dias(dias)
    now = datetime.now()
    umbral = now - timedelta(days=dias)
    runs_root = base / "outputs" / "runs"
    resumen = {"archivados": 0, "borrados": 0, "pdf_enlaces": 0, "errores": []}
    if runs_root.is_dir():
        for ruta in sorted(runs_root.iterdir()):
            if not ruta.is_dir() or ruta.is_symlink() or not RUN_ID_RE.fullmatch(ruta.name):
                continue
            if lote_en_ejecucion(ruta):
                continue
            try:
                if _fecha_lote(ruta.name, ruta) > umbral:
                    continue
                archivar_lote(base, ruta.name)
                resumen["archivados"] += 1
                # Tras el recibo, se pueden eliminar PDFs Y artefactos pesados.
                # El resumen histórico permanece en historial/ y Firestore.
                for candidato in (base / "uploads" / ruta.name, ruta):
                    if candidato.exists():
                        _borrar_path(candidato)
                resumen["borrados"] += 1
            except Exception as exc:
                resumen["errores"].append(f"{ruta.name}: {exc}")
    # Enlaces estáticos de PDF pueden ser hardlinks que retengan bytes incluso
    # después de borrar uploads. Solo caducan pasados los mismos N días.
    static = base / "static" / "pdfs"
    if static.is_dir():
        for carpeta in static.iterdir():
            if carpeta.is_symlink() or not carpeta.is_dir():
                continue
            try:
                if datetime.fromtimestamp(carpeta.stat().st_mtime) < umbral:
                    _borrar_path(carpeta)
                    resumen["pdf_enlaces"] += 1
            except OSError as exc:
                resumen["errores"].append(f"{carpeta.name}: {exc}")
    # Descargas estáticas legadas: también ocupan espacio en versiones
    # anteriores. Solo eliminar las que tengan recibo de historial confirmado.
    exportaciones = base / "static" / "exports"
    if exportaciones.is_dir():
        for ruta_export in exportaciones.iterdir():
            if not ruta_export.is_dir() or ruta_export.is_symlink():
                continue
            try:
                recibo = base / CARPETA_HISTORIAL / "recibos" / f"{ruta_export.name}.json"
                if (recibo.is_file()
                        and datetime.fromtimestamp(ruta_export.stat().st_mtime) < umbral):
                    _borrar_path(ruta_export)
            except OSError as exc:
                resumen["errores"].append(f"exports/{ruta_export.name}: {exc}")
    return resumen


def mantenimiento_periodico(base: Path, dias: int = 3, intervalo_horas: int = 12) -> dict:
    """Limpieza automática al usar homcloud, sin dos sesiones compitiendo.

    No es un cron de Google: si Cloud Shell está apagado, se ejecuta al
    siguiente inicio o interacción que rerenderice la aplicación.
    """
    validar_dias(dias)
    carpeta = base / CARPETA_HISTORIAL
    carpeta.mkdir(parents=True, exist_ok=True)
    lock_path = carpeta / ".mantenimiento.lock"
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"omitido": True, "errores": []}
        try:
            estado_path = carpeta / "ultimo_mantenimiento.json"
            if estado_path.is_file():
                try:
                    estado = json.loads(estado_path.read_text(encoding="utf-8"))
                    if (estado.get("dias") == dias
                            and time.time() - float(estado["timestamp"]) < intervalo_horas * 3600):
                        return {"omitido": True, "errores": []}
                except (ValueError, TypeError, OSError, KeyError):
                    pass
            resultado = limpiar_antiguos(base, dias)
            # Si hubo errores, volver a intentarlo en la próxima ejecución.
            if not resultado["errores"]:
                temporal = estado_path.with_suffix(".tmp")
                try:
                    temporal.write_text(
                        json.dumps({"timestamp": time.time(), "dias": dias}),
                        encoding="utf-8",
                    )
                    os.replace(temporal, estado_path)
                finally:
                    temporal.unlink(missing_ok=True)
            return resultado
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def importar_lotes_existentes(base: Path) -> dict:
    """Migra histórico previo sin borrar PDFs, útil para ambas cuentas."""
    runs = base / "outputs" / "runs"
    resultado = {"archivados": 0, "omitidos_activos": 0, "errores": []}
    if not runs.is_dir():
        return resultado
    for ruta in sorted(runs.iterdir()):
        if not ruta.is_dir() or ruta.is_symlink() or not RUN_ID_RE.fullmatch(ruta.name):
            continue
        if lote_en_ejecucion(ruta):
            resultado["omitidos_activos"] += 1
            continue
        try:
            archivar_lote(base, ruta.name)
            resultado["archivados"] += 1
        except Exception as exc:
            resultado["errores"].append(f"{ruta.name}: {exc}")
    return resultado


def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Historial y retención de homcloud")
    parser.add_argument(
        "accion", choices=("importar", "limpiar", "estado"),
        help="importar conserva todos los archivos; limpiar archiva antes de borrar",
    )
    parser.add_argument("--dias", type=int, default=3)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    if args.accion == "importar":
        respuesta = importar_lotes_existentes(base)
    elif args.accion == "limpiar":
        respuesta = limpiar_antiguos(base, dias=args.dias)
    else:
        raiz = base / "outputs" / "runs"
        respuesta = {
            "lotes_en_disco": len([p for p in raiz.iterdir() if p.is_dir()]) if raiz.is_dir() else 0,
            "historial_local": str(base / CARPETA_HISTORIAL / NOMBRE_CSV),
            "dias_predeterminados": RETENCION_DIAS_DEFAULT,
        }
    print(json.dumps(respuesta, ensure_ascii=False, indent=2))
    return 1 if respuesta.get("errores") else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
