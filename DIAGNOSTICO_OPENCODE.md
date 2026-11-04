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

## Si la prueba no muestra nada y presionas Ctrl+C

El 4 de noviembre de 2026 las pruebas de DeepSeek y GLM se interrumpieron
manualmente (el `KeyboardInterrupt` no era la respuesta del modelo).
Además, el incidente oficial de inferencia gratuita del 3 de noviembre,
20:28–21:22 UTC, coincide con el inicio del lote problemático de las
15:47 hora de Colombia. No es prueba de la causa específica, pero sí
un antecedente externo muy relevante:
[Estado de OpenCode](https://status.opencode.ai/).

La versión actual muestra un **heartbeat cada cinco segundos**:
tiempo transcurrido, stdout/stderr en bytes, inactividad y categoría
del error. Se limita por sí sola al tiempo definido con `--timeout`.
Si presionas `Ctrl+C`, **cierra el proceso hijo** y devuelve un resumen
legible en vez de un traceback.

Antes de probar de nuevo:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_diagnostico_opencode test_integridad_app -v
# Muestra procesos por nombre, NO argumentos con prompts de estudiantes.
ps -eo pid,ppid,etime,stat,comm | grep -E '(^ *PID|opencode)'
# Lista los proveedores autenticados, sin imprimir claves privadas.
opencode auth list
.venv/bin/python -m diagnostico_opencode probar \
  --model opencode/deepseek-v4.1-flash-free --timeout 30
.venv/bin/python -m diagnostico_opencode probar \
  --model opencode/glm-5.3-flash-free --timeout 30
```

No cambies los timeouts del procesamiento diario hasta interpretar los
resultados de estas pruebas simples. Si ambos modelos expiran con
stdout=0, stderr=0, comprueba autenticación y acceso a los proveedores;
el listado de modelos no garantiza que puedas inferir con ellos.
No elimines archivos de credenciales ni reinicies procesos de un lote
activo a ciegas.

## Actualización a OpenCode 2.2.5: el siguiente fallo es distinto

La instalación de `auxiliarregistroycontrol24` ya se actualizó a
**OpenCode v2.2.5**, pero la prueba de GLM terminó tras **10 segundos
con código 1, stdout=0 y stderr=161 bytes**. Esto no fue un timeout:
la CLI terminó con error. El diagnóstico anterior resumía ese stderr como
«Sin error reconocible» y no permitía identificar la causa exacta.

Un antecedente importante: `opencode auth list` mostró
**0 credentials**. Hay una incidencia documentada en OpenCode v2:
sin credenciales guardadas para el proveedor Console, los modelos gratuitos
pueden fallar con mensajes confusos, y en esos casos el login
`opencode auth login opencode` solucionó el fallo. Véase
[issue 52917](https://github.com/anomalyco/opencode/issues/52917)
y [issue 55619](https://github.com/anomalyco/opencode/issues/55619).
**Aún no está demostrado que sea el error de este Cloud Shell**:
es necesario revisar stderr sin compartir secretos.

Procedimiento, sin documentos académicos:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_diagnostico_opencode -v
opencode auth login opencode
opencode auth list
.venv/bin/python -m diagnostico_opencode probar \
  --model opencode/glm-5.3-flash-free --timeout 45
```

Completa el flujo de login en el navegador o terminal. No hay que compartir
claves, códigos de acceso ni `auth.json`. Si la prueba falla, ahora
imprime **un fragmento redactado del stderr de la prueba sintética**.
Este detalle solo se muestra para la instrucción inocua «OK», nunca
para el procesamiento real de PDFs. Revisa cualquier texto antes de
copiarlo fuera de Cloud Shell.

Si falla aun autenticado, revisa la opción
`opencode run --help`, el entorno de proyecto y posibles restricciones
por IP del proveedor. **No proceses nuevos lotes** hasta ver
`respondio_prueba: true`.

## Causa detectada el 4 de noviembre: OpenCode 1.19.5

La cuenta secundaria mostró OpenCode **1.19.5**, y pruebas de 30 segundos
tanto con `opencode/deepseek-v4.1-flash-free` como con
`opencode/glm-5.3-flash-free` acabaron en timeout, stdout=0.
En el repositorio oficial se explicó el 28 de octubre de 2026 que **OpenCode
v1 ya no admite los modelos gratuitos**:
[issue #59975](https://github.com/anomalyco/opencode/issues/59975).
La migración a v2 es prioritaria antes de seguir aumentando timeouts.
También hay [restricciones confirmadas por IP de red para modelos gratuitos](https://github.com/anomalyco/opencode/issues/56719),
por lo que v2 puede seguir fallando desde algunas redes de centros de datos.

El comando oficial de actualización mayor de OpenCode v1 es:

```bash
opencode upgrade --major
opencode --version  # debe mostrar 2.x
```

Antes de actualizar, comprueba que no haya un lote activo y conserva una copia
privada de la configuración y datos locales de autenticación. No compartas
ficheros `auth.json`, claves ni registros completos.

**homcloud tiene compatibilidad de comandos v1/v2:** detecta la versión,
y en v2 ejecuta `opencode run --standalone --file <txt> --model <modelo>
<prompt>` con cwd aislado; no utiliza la antigua opción `--dir`.
Las pruebas unitarias garantizan la construcción de comandos, pero no
sustituyen una prueba real del servicio desde Cloud Shell. El modo aislado
puede requerir más recursos que v1, así que prueba inicialmente con
**concurrencia de 1**.

Después de actualizar el repositorio y la CLI:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_opencode_compat test_diagnostico_opencode test_integridad_app -v
opencode --version
.venv/bin/python -m diagnostico_opencode probar \
  --model opencode/glm-5.3-flash-free --timeout 60
```

No proceses lotes grandes hasta confirmar `respondio_prueba: true`.
Si v2 no responde y no hay credenciales locales, revisa `opencode auth
list` y la configuración de acceso con el proveedor antes de concluir
que se trata de una caída general.

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
