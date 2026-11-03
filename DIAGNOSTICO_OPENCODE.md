# Diagnóstico de OpenCode en homcloud

## Por qué un lote puede permanecer en «OpenCode CLI»

En el lote revisado del **3 de noviembre de 2026** se observaron 19 filas:
10 archivos pasaron 5 minutos en la fase OpenCode hasta el timeout externo
`Error timeout lote`, y otros 9 quedaron `Error no iniciado` porque
ninguno de los 10 workers quedó libre. El modelo era
`opencode/deepseek-v4.1-flash-free`.

Eso **no demuestra por sí mismo** si hubo saturación 429, 5xx, error de red,
bucle de generación o tardanza del proveedor. En versiones anteriores
`subprocess.communicate()` solo recogía stdout/stderr cuando OpenCode
terminaba, mientras que el watchdog del PDF podía marcar timeout y cerrar
la fila **antes** del timeout propio de OpenCode.

## Qué cambia

- Cada worker registra `opencode_diagnostico.json`, `opencode_stdout.log`
  y `opencode_stderr.log` en su subcarpeta `outputs/runs/<lote>/_workers/`.
- Se actualizan periódicamente los bytes de salida, segundos sin producir
  salida, PID, estado, duración, código de salida y clasificación de errores
  reconocibles. El JSON **no guarda el prompt** ni la respuesta de la IA.
- OpenCode imprime advertencias/errores a stderr con las opciones documentadas
  `--print-logs --log-level WARN`. Sus logs originales pueden contener datos
  confidenciales, y NO se envían a Firestore ni aparecen en la tabla pública.
- Si el timeout externo vence, se cancela el subproceso de OpenCode y su grupo
  con señal de terminación. Se intenta liberar el marcador de actividad una
  vez comprobado que los workers finalizaron.
- La página lateral **Diagnóstico OpenCode** muestra solo el resumen seguro.
  Abre la página en una **segunda pestaña** mientras la primera procesa PDFs.
- Los logs del worker se eliminan con los archivos temporales del lote
  después del período de retención configurado (3 días por defecto).

## Primer diagnóstico sin consumir un lote de documentos

En el Cloud Shell que presenta el problema:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_diagnostico_opencode test_integridad_app -v
opencode --version
opencode models opencode | grep -E 'deepseek-v4.1-flash-free|glm-5.3-flash-free'
.venv/bin/python -m diagnostico_opencode logs --horas 24
.venv/bin/python -m diagnostico_opencode probar \
  --model opencode/deepseek-v4.1-flash-free --timeout 90
```

El comando `probar` manda únicamente «Responde únicamente con la palabra OK.»,
sin ningún PDF ni dato de estudiante. Devuelve clasificación, tiempo, código
de salida y tamaños, sin publicar la respuesta textual. La prueba de 90 s
limita el tiempo dedicado a verificar el modelo, no modifica configuraciones
persistentes de homcloud.

**Si falla la prueba de DeepSeek**, y el catálogo local contiene
`opencode/glm-5.3-flash-free`, ejecuta la misma prueba con ese otro modelo:

```bash
.venv/bin/python -m diagnostico_opencode probar \
  --model opencode/glm-5.3-flash-free --timeout 90
```

Si la alternativa responde y el modelo original no, es un indicio importante
de un problema específico del modelo/proveedor, y no de LLMWhisperer o los PDFs.
Revisa la política de uso de datos del proveedor antes de enviar actas
académicas a un modelo distinto.

Después, prueba **un solo PDF** con **1 proceso simultáneo**, OpenCode
**5 minutos** y PDF activo **15 minutos**. Abrir
«Diagnóstico OpenCode» durante la ejecución permitirá observar si hay una
respuesta que crece, ausencia prolongada de salida o error 429/5xx.

El límite de PDF activo debe superar el límite propio de OpenCode y dejar
margen a la extracción previa con LLMWhisperer. Un límite de PDF de 5 minutos
junto a uno de OpenCode de 15 no permite a OpenCode alcanzar su propio timeout,
por lo que el error queda registrado como timeout externo.

## Interpretación responsable

| Indicador | Qué sugiere |
|---|---|
| HTTP 429 / cuota | Probable limitación de velocidad/cupo del proveedor; reducir concurrencia y revisar política |
| HTTP 5xx | Servicio remoto con problemas |
| HTTP 401 / 403 | Problema de autorización o permisos del modelo |
| Sin mensajes en stderr, stdout=0 | OpenCode sigue sin entregar salida; puede ser espera remota, inicio, bloqueo o reintento silencioso |
| stdout crece hasta límite | Posible respuesta repetitiva o excesiva |
| cancelado_por_timeout_del_lote | El watchdog del PDF alcanzó primero su límite; **no es una explicación del proveedor** |
| timeout_opencode | Terminó el timeout propio de OpenCode |
| código de salida 0 | El proceso terminó; aún debe validarse que la respuesta sea JSON correcto |

Los códigos se detectan de forma heurística en stderr; un «Sin mensajes»
**no implica** que el proveedor esté sano. El diagnóstico consulta un lote
local, no los datos del otro Cloud Shell.

Para un lote creado **después** de actualizar:

```bash
.venv/bin/python -m diagnostico_opencode lote ID_DEL_LOTE
```

Lotes anteriores a esta implementación **no tienen telemetría retrospectiva**.
El comando `logs --horas 24` puede detectar errores en los logs históricos
de OpenCode, pero no asignarlos con certeza a un PDF específico.

**Privacidad:** comparte con soporte únicamente la salida JSON resumida de
`logs`, `probar` o `lote`. No compartas los archivos de stdout/stderr,
el TXT extraído, las actas, los prompts completos ni claves API.

Fuentes: [OpenCode CLI](https://opencode.ai/docs/es/cli/),
[OpenCode Troubleshooting](https://opencode.ai/docs/es/troubleshooting/).
