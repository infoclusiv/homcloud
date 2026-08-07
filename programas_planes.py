from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import unicodedata


PROGRAMAS_PLANES_CONFIG_VERSION = 3
CAMPO_PERMITIR_PLAN_VACIO = "Permitir plan vacío"

PROGRAMA_SST_PREGRADO = "Seguridad y Salud en el Trabajo Virtual"
PROGRAMA_SST_POSGRADO = (
    "Especialización en Gerencia de la Seguridad y Salud en el Trabajo Virtual"
)
_ALIAS_SST_PREGRADO = {
    "seguridad y salud en el trabajo",
    "seguridad y salud en el trabajo virtual",
}
_OFICIALES_SST_POSGRADO_ANTERIORES = {
    "especializacion en seguridad y salud en el trabajo",
    "especializacion en seguridad y salud en el trabajo virtual",
    "especializacion en gerencia de la seguridad y salud en el trabajo virtual",
}


def _programa(nombre: str, plan: str, alias: str = "", permitir_vacio: bool = False):
    return {
        "Programa al que aspira": nombre,
        "Plan": plan,
        "Alias": alias,
        CAMPO_PERMITIR_PLAN_VACIO: permitir_vacio,
    }


PROGRAMAS_PLANES_DEFAULT = [
    _programa(
        "Administración Logística",
        "P2",
        "Adm logística; Admon logística; Administración de logística",
    ),
    _programa(
        "Marketing y Negocios Internacionales",
        "P2",
        "Mkt y negocios; Marketing y negocios; Mkt y negocios internacionales",
    ),
    _programa("Psicología", "P4"),
    _programa(
        PROGRAMA_SST_POSGRADO,
        "P2",
        (
            "Especialización en Seguridad y Salud en el Trabajo; "
            "Especialización en Seguridad y Salud en el Trabajo Virtual; "
            "Esp seg y salud trabajo; Esp seguridad y salud trabajo; "
            "Especialización SST; Esp SST; ESP GCIA SEG SALUD EN TRA VIRT"
        ),
    ),
    _programa(
        "Especialización en Gerencia de la Calidad en Salud",
        "P2",
        "Esp calidad en salud; Esp gerencia calidad en salud; Esp gerencia de la calidad en salud; Especialización en calidad en salud",
    ),
    _programa(
        "Especialización en Audiología",
        "P2",
        "Esp en audiologia; Esp audiologia; Especialización Audiología",
    ),
    _programa(
        "Especialización en Gerencia Financiera",
        "P2",
        "Esp gerencia finaciera; Esp gerencia financiera; Especialización gerencia financiera",
    ),
    _programa(
        "Especialización en Desarrollo Integral de la Infancia y la Adolescencia",
        "P2",
        "Esp desarrollo integral de infancia y adolesencia; Esp desarrollo integral de infancia y adolescencia; Desarrollo integral infancia adolescencia",
    ),
    _programa("Fonoaudiología", "P5"),
    _programa("Fisioterapia", "P5"),
    _programa("Contaduría Pública", "P2", "Contaduría; Contaduria"),
    _programa(
        "Licenciatura en Educación Infantil",
        "P1",
        "Lic en educación infantil; Lic educación infantil; Licenciatura educación infantil; Licenciatura en Infantil",
        True,
    ),
    _programa(
        "Licenciatura en Humanidades y Lengua Castellana",
        "P2",
        "Lic en humanidades y lengua castellana; Lic humanidades y lengua castellana; Licenciatura humanidades y lengua castellana",
        True,
    ),
    _programa("Maestría en Educación", "P2", "Maestría Educación; Maestria educacion"),
    _programa(
        "Administración de Empresas",
        "P1",
        "Administración de Empresas Virtual",
        True,
    ),
    _programa("Ingeniería de Sistemas", "P1", permitir_vacio=True),
    _programa("Ingeniería de Software", "P1", "De Software", True),
    _programa("Ingeniería Industrial", "P1", permitir_vacio=True),
    _programa("Ingeniería en Ciencia de Datos", "P1", permitir_vacio=True),
    _programa("Licenciatura en Ciencias Sociales", "P1", permitir_vacio=True),
    _programa("Licenciatura en Matemáticas", "P1", permitir_vacio=True),
    _programa("Mercadeo y Publicidad", "P1", permitir_vacio=True),
    _programa("Negocios Internacionales", "P1", permitir_vacio=True),
    _programa("Derecho", "P1", permitir_vacio=True),
    _programa(
        "Administración Financiera",
        "P1",
        "Administración Financiera Virtual; Financiera Virtual; Adminsitración Financiera",
        True,
    ),
    _programa(
        "Administración en Salud",
        "P1",
        "Administración en Salud Virtual",
        True,
    ),
    _programa("Especialización en Auditoría en Salud", "P1", permitir_vacio=True),
    _programa(
        "Especialización en Marketing Digital",
        "P1",
        "Esp en Marketing Digital Vir",
        True,
    ),
    _programa(
        "Especialización en Gerencia de Proyectos",
        "P1",
        "Esp Gerencia de Proyectos Vir",
        True,
    ),
    _programa("Especialización en Ciberseguridad", "P1", permitir_vacio=True),
    _programa(
        "Especialización en Neuropsicología de la Educación",
        "P1",
        permitir_vacio=True,
    ),
    _programa(
        PROGRAMA_SST_PREGRADO,
        "P1",
        "Seguridad y Salud en el Trabajo",
        True,
    ),
    _programa("Maestría en Gerencia de Proyectos", "P1", permitir_vacio=True),
    _programa("Trabajo Social Virtual", "P1", permitir_vacio=True),
    _programa(
        "Especialización en Analítica y Big Data",
        "P1",
        "Especialización en Analítica Virtual y Big Data",
        True,
    ),
]


def _normalizar_texto(valor) -> str:
    texto = str(valor or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_programa(valor) -> str:
    texto = re.sub(r"[^a-z0-9]+", " ", _normalizar_texto(valor))
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_plan(valor) -> str:
    texto = re.sub(r"^(?:plan|p)\s*", "", _normalizar_texto(valor))
    return re.sub(r"[^a-z0-9]+", "", texto)


def normalizar_booleano(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return False
    if isinstance(valor, (int, float)):
        try:
            return bool(valor) and not (valor != valor)
        except TypeError:
            return bool(valor)

    return _normalizar_texto(valor) in {
        "1", "si", "sí", "true", "verdadero", "yes", "x",
    }


def separar_alias(valor) -> list[str]:
    candidatos = (
        valor
        if isinstance(valor, (list, tuple, set))
        else re.split(r"[;\n]+", str(valor or ""))
    )
    resultado = []
    vistos = set()
    for candidato in candidatos:
        alias = str(candidato or "").strip()
        clave = normalizar_programa(alias)
        if clave and clave not in vistos:
            vistos.add(clave)
            resultado.append(alias)
    return resultado


def _convertir_editor_a_registros(datos) -> list[dict]:
    if datos is None:
        return []
    if hasattr(datos, "to_dict"):
        try:
            return datos.to_dict("records")
        except TypeError:
            pass
    if isinstance(datos, dict):
        return [datos]
    if isinstance(datos, (list, tuple)):
        return [fila for fila in datos if isinstance(fila, dict)]
    return []


def validar_programas_planes(datos) -> list[dict]:
    filas_limpias = []
    nombres_vistos = {}

    for numero_fila, fila in enumerate(_convertir_editor_a_registros(datos), 1):
        programa = str(fila.get("Programa al que aspira", "") or "").strip()
        plan = str(fila.get("Plan", "") or "").strip()
        alias = separar_alias(fila.get("Alias", ""))
        permitir_vacio = normalizar_booleano(
            fila.get(CAMPO_PERMITIR_PLAN_VACIO, False)
        )

        if not programa and not plan and not alias:
            continue
        if not programa or not plan:
            raise ValueError(
                f"La fila {numero_fila} debe incluir tanto el programa como el plan."
            )

        clave_programa = normalizar_programa(programa)
        clave_plan = normalizar_plan(plan)
        if not clave_programa:
            raise ValueError(f"El programa de la fila {numero_fila} no es válido.")
        if not clave_plan:
            raise ValueError(f"El plan de la fila {numero_fila} no es válido.")

        nombres_fila = [(programa, clave_programa)] + [
            (nombre_alias, normalizar_programa(nombre_alias))
            for nombre_alias in alias
        ]
        claves_fila = set()
        alias_limpios = []

        for nombre_visible, clave_nombre in nombres_fila:
            if not clave_nombre or clave_nombre in claves_fila:
                continue
            claves_fila.add(clave_nombre)

            if clave_nombre in nombres_vistos:
                fila_anterior, programa_anterior = nombres_vistos[clave_nombre]
                raise ValueError(
                    f"El nombre o alias '{nombre_visible}' de la fila {numero_fila} "
                    f"ya pertenece a '{programa_anterior}' en la fila {fila_anterior}."
                )

            nombres_vistos[clave_nombre] = (numero_fila, programa)
            if clave_nombre != clave_programa:
                alias_limpios.append(nombre_visible)

        filas_limpias.append({
            "Programa al que aspira": programa,
            "Plan": f"P{clave_plan}" if clave_plan.isdigit() else plan,
            "Alias": "; ".join(alias_limpios),
            CAMPO_PERMITIR_PLAN_VACIO: permitir_vacio,
        })

    return sorted(
        filas_limpias,
        key=lambda fila: normalizar_programa(fila["Programa al que aspira"]),
    )


def _unir_alias(programa_oficial: str, *grupos_alias) -> str:
    vistos = {normalizar_programa(programa_oficial)}
    resultado = []

    for grupo in grupos_alias:
        for alias in separar_alias(grupo):
            clave = normalizar_programa(alias)
            if clave and clave not in vistos:
                vistos.add(clave)
                resultado.append(alias)

    return "; ".join(resultado)


def _migrar_seguridad_salud_v3(datos) -> list[dict]:
    resultado = [dict(fila) for fila in validar_programas_planes(datos)]
    claves_posgrado = {
        normalizar_programa(nombre)
        for nombre in _OFICIALES_SST_POSGRADO_ANTERIORES
    }
    claves_pregrado = {
        normalizar_programa(nombre)
        for nombre in _ALIAS_SST_PREGRADO
    }

    for fila in resultado:
        clave_oficial = normalizar_programa(fila["Programa al que aspira"])
        if clave_oficial not in claves_posgrado:
            continue

        alias_preservados = [
            alias
            for alias in separar_alias(fila.get("Alias", ""))
            if normalizar_programa(alias) not in claves_pregrado
        ]
        alias_preservados.append(fila["Programa al que aspira"])
        fila["Programa al que aspira"] = PROGRAMA_SST_POSGRADO
        fila["Plan"] = "P2"
        fila[CAMPO_PERMITIR_PLAN_VACIO] = False
        fila["Alias"] = _unir_alias(
            PROGRAMA_SST_POSGRADO,
            alias_preservados,
            (
                "Especialización en Seguridad y Salud en el Trabajo; "
                "Especialización en Seguridad y Salud en el Trabajo Virtual; "
                "Esp seg y salud trabajo; Esp seguridad y salud trabajo; "
                "Especialización SST; Esp SST; ESP GCIA SEG SALUD EN TRA VIRT"
            ),
        )

    return validar_programas_planes(resultado)


def migrar_programas_planes(datos) -> list[dict]:
    resultado = _migrar_seguridad_salud_v3(datos)
    indices_por_nombre = {}

    for indice, fila in enumerate(resultado):
        nombres = [fila["Programa al que aspira"]] + separar_alias(fila.get("Alias", ""))
        for nombre in nombres:
            indices_por_nombre.setdefault(normalizar_programa(nombre), set()).add(indice)

    for predeterminado in validar_programas_planes(PROGRAMAS_PLANES_DEFAULT):
        nombres_default = [
            predeterminado["Programa al que aspira"],
            *separar_alias(predeterminado.get("Alias", "")),
        ]
        candidatos = set()
        for nombre in nombres_default:
            candidatos.update(indices_por_nombre.get(normalizar_programa(nombre), set()))

        if len(candidatos) > 1:
            programas = ", ".join(
                resultado[indice]["Programa al que aspira"]
                for indice in sorted(candidatos)
            )
            raise ValueError(
                "No se puede migrar la configuración porque una relación "
                f"predeterminada coincide con varias filas: {programas}."
            )

        if not candidatos:
            resultado.append(dict(predeterminado))
            indice = len(resultado) - 1
        else:
            indice = next(iter(candidatos))
            existente = resultado[indice]
            existente["Alias"] = _unir_alias(
                existente["Programa al que aspira"],
                existente.get("Alias", ""),
                predeterminado["Programa al que aspira"],
                predeterminado.get("Alias", ""),
            )
            if predeterminado[CAMPO_PERMITIR_PLAN_VACIO]:
                existente["Plan"] = predeterminado["Plan"]
                existente[CAMPO_PERMITIR_PLAN_VACIO] = True

        fila_actualizada = resultado[indice]
        for nombre in [
            fila_actualizada["Programa al que aspira"],
            *separar_alias(fila_actualizada.get("Alias", "")),
        ]:
            indices_por_nombre.setdefault(normalizar_programa(nombre), set()).add(indice)

    return validar_programas_planes(resultado)


def cargar_programas_planes(path: Path) -> list[dict]:
    try:
        if not path.exists():
            return guardar_programas_planes(PROGRAMAS_PLANES_DEFAULT, path)

        contenido = json.loads(path.read_text(encoding="utf-8"))
        version = 0
        if isinstance(contenido, dict):
            version = int(contenido.get("version", 0) or 0)
            datos = contenido.get("programas", [])
        else:
            datos = contenido

        if version < PROGRAMAS_PLANES_CONFIG_VERSION:
            migrados = migrar_programas_planes(datos)
            try:
                guardar_programas_planes(migrados, path)
            except OSError:
                pass
            return migrados

        return validar_programas_planes(datos)
    except Exception:
        return validar_programas_planes(PROGRAMAS_PLANES_DEFAULT)


def guardar_programas_planes(datos, path: Path) -> list[dict]:
    filas_limpias = validar_programas_planes(datos)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": PROGRAMAS_PLANES_CONFIG_VERSION,
                "programas": filas_limpias,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return filas_limpias


def construir_mapa_programas_planes(configuracion) -> dict[str, dict[str, object]]:
    mapa = {}

    for fila in validar_programas_planes(configuracion):
        nombres = [fila["Programa al que aspira"]] + separar_alias(fila.get("Alias", ""))
        for nombre in nombres:
            mapa[normalizar_programa(nombre)] = {
                "programa_oficial": fila["Programa al que aspira"],
                "plan": fila["Plan"],
                "permitir_plan_vacio": fila[CAMPO_PERMITIR_PLAN_VACIO],
            }

    return mapa


def evaluar_plan(
    programa,
    plan,
    mapa_programas_planes: dict[str, dict[str, object]],
) -> str:
    programa_normalizado = normalizar_programa(programa)
    plan_normalizado = normalizar_plan(plan)

    if not programa_normalizado and not plan_normalizado:
        return "sin_datos"

    coincidencia = mapa_programas_planes.get(programa_normalizado)
    if coincidencia is None:
        return "sin_configuracion"

    if not plan_normalizado and coincidencia.get("permitir_plan_vacio", False):
        return "correcto"

    if plan_normalizado == normalizar_plan(coincidencia["plan"]):
        return "correcto"

    return "incorrecto"
