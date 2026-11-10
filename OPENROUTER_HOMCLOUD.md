# OpenRouter en homcloud — modelos gratuitos y de pago

## Configuración desde la interfaz

1. Actualiza el repositorio en tu Cloud Shell y abre la aplicación.
2. **Por defecto está seleccionado OpenRouter → `deepseek/deepseek-v4-flash-0731` (de pago)**. No hace falta volver a configurarlo en cada entrada.
3. Si ya guardaste tu API key con **Guardar API key permanentemente**, se recuperará automáticamente.
4. **Carga los PDFs/Excel y pulsa Iniciar procesamiento**. No se mostrarán confirmaciones repetitivas por envío de documentos ni por usar este modelo facturable.
5. Si deseas cambiar el proveedor o el modelo, utiliza el selector: muestra Todos, Gratis y Pago y guarda la última selección automáticamente en este Cloud Shell.
6. Revisa los precios antes de cambiar a otros modelos de pago. La aplicación utiliza el modelo escogido y OpenRouter puede cobrar por tokens; configura un límite monetario en tu cuenta de OpenRouter.

El catálogo procede del endpoint oficial `GET /api/v1/models`; permite TODOS los modelos compatibles con texto, no solamente `:free`. Muestra precios USD por millón de tokens de entrada y salida cuando están disponibles; esos precios no son un techo de gasto. **Por petición expresa del propietario, los modelos de pago que seleccione están autorizados para procesar documentos sin casilla adicional.** Las pruebas sintéticas con modelos de pago también pueden consumir créditos.

## API key: archivo privado, no código versionado

La clave se guarda en `settings/openrouter_api_key.txt` dentro del Cloud Shell que utiliza la web, con permisos `0600`. Se reutiliza al reiniciar el programa. El archivo está ignorado por Git y no se envía a GitHub ni Firestore. Nunca coloques claves en `app.py` ni en ningún archivo versionado.

**Importante (corrección de autenticación):** homcloud ahora da prioridad a la clave guardada desde la web en `settings/openrouter_api_key.txt`. Si no existe, usa `OPENROUTER_API_KEY` desde el entorno o el `.env` privado. Esto evita que una clave antigua del entorno anule la que acabas de guardar. Si hay una clave temporal escrita en el campo de la interfaz, esa clave tiene prioridad durante esa sesión, hasta que pulses Guardar.

Las dos cuentas de Cloud Shell tienen entornos independientes, por lo que cada una guarda su propia clave una vez.

Crea tus credenciales en https://openrouter.ai/settings/keys. No compartas claves ni archivos de respaldo que las contengan.

## Diagnosticar errores HTTP 401 sin enviar documentos

OpenRouter publica un endpoint de verificación autenticada `GET /api/v1/key`
que **no ejecuta inferencia ni consume tokens**. El catálogo
`GET /api/v1/models` es público: poder listar modelos **no** prueba
que la clave de usuario sea válida.

En la web: abre **OpenRouter → Credenciales OpenRouter** y pulsa
**Verificar API key sin consumir tokens**. La interfaz muestra solamente
HTTP 200/401, estado, y de qué fuente se cargó la clave, sin revelar
su contenido. Si vas a sustituir una clave inválida, pégala en el campo
y pulsa **Guardar API key permanentemente en este Cloud Shell**.

Desde el Cloud Shell donde ocurre el error:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m openrouter_cliente verificar
```

Para la cuenta `infoclusiv` la ruta es `~/llmwhisperer-pdf-parser`.
El comando solo emite información diagnóstica segura.

Interpretación:
- **HTTP 200:** esa clave existe y OpenRouter la reconoce. Si el modelo
  sigue fallando, prueba un modelo ficticio y consulta su error específico.
  Después de esta corrección, la validación, la prueba sintética, el
  procesamiento y los reintentos usan la misma clave persistente. La
  clave recién escrita en el campo contraseña **no se utilizará en el
  procesamiento hasta pulsar Guardar**.
  Antes de iniciar un lote OpenRouter se consulta /api/v1/key de nuevo
  para evitar extracciones innecesarias si la clave ya no funciona.
- **HTTP 401 en GET /key:** clave ausente, incorrecta, revocada o caducada.
  Si GET /key devuelve 200 pero POST /chat/completions devuelve 401
  utilizando la **misma** clave, se debe revisar la autorización de
  inferencia, el modelo o el proveedor. No sustituir la clave sin evidencia.
  Crea una nueva desde https://openrouter.ai/settings/keys.
- **HTTP 402:** problema de créditos/saldo; diferente de HTTP 401.
- **HTTP 429:** límite de solicitudes; diferente de HTTP 401.
- **Sin respuesta HTTP:** investigar conexión, DNS o proxy.

En las claves creadas desde OpenRouter normalmente se usa el prefijo
`sk-or-v1-`. **No pegues** la palabra `Bearer` ni comillas: homcloud
agrega automáticamente el encabezado HTTP. Nunca compartas la clave
completa, `.env`, `settings/openrouter_api_key.txt` ni los logs crudos.

## Modelo predeterminado y selección persistente

Al abrir homcloud, el motor inicial es:

```text
openrouter::deepseek/deepseek-v4-flash-0731
```

**Se ejecuta de forma síncrona**, sin la espera de `:batch`, y está
disponible desde el endpoint `/api/v1/chat/completions`. Esta decisión
se implementó después de comprobar una respuesta HTTP 200 en menos de
un segundo con un mensaje ficticio desde el Cloud Shell del propietario.

La preferencia se almacena en un archivo local diferente a la
configuración legada de OpenCode:

```text
settings/motor_ia_preferido.txt
```

Se utiliza el modelo predeterminado si ese archivo aún no existe.
Al cambiar de modelo o proveedor, el programa actualiza el archivo
automáticamente. El archivo está en `.gitignore`, por lo que no se
versiona ni sobrescribe con `git pull`. El modelo global anterior de
Firestore ya no desplaza el elegido en este Cloud Shell, aunque los
prompts y los timeouts globales continúan funcionando. La configuración
global de modelo puede seguir publicándose expresamente desde el sidebar;
cada cuenta mantiene su selección propia.

Como el uso facturable ya está autorizado para el flujo diario,
**seleccionar otro modelo de pago puede generar cargos** al iniciar
un lote. El botón Iniciar procesamiento es la acción explícita que
envía los datos y genera los cargos aplicables. Se recomienda un
límite de gasto en https://openrouter.ai/settings/keys.
No se realizan solicitudes de inferencia solo por abrir la aplicación.

## Interfaz más compacta

En Inicio se conservan solamente los controles de trabajo diario: concurrencia, proveedor/modelo, carga de PDFs o Excel, progreso, resumen, errores, reintentos y descargas.

El sidebar añade las páginas:
- **Programas y planes**: editor completo y gestión del catálogo.
- **Configuración operativa**: predeterminados globales, retención y limpieza manual.

Las opciones de sincronización, prompts, timeouts y publicación global del modelo quedan en desplegables del sidebar. Esto evita que un editor de programas colapsado deje un gran espacio vacío al lado de un bloque de configuración mucho más alto.

## Integración y privacidad

Con OpenRouter seleccionado se mantiene el flujo de LLMWhisperer → TXT → contrato JSON → validación Python → AHK + CSV + historial. El propietario autorizó de forma permanente el envío de sus documentos a OpenRouter y el uso de modelos de pago, por lo que ya no hay casillas de aprobación en cada sesión o reintento. La interfaz limita de forma conservadora a 2 las llamadas simultáneas a OpenRouter.

Los TXT incluyen potencialmente datos personales académicos y serán transmitidos a OpenRouter y al proveedor seleccionado. Verifica la política institucional, las condiciones de retención de cada proveedor, la privacidad del modelo concreto y la autorización antes de enviar documentos reales.

## Modelos :batch: prueba específica y limitación del procesador web

El identificador `deepseek/deepseek-v4.1-flash-1017:batch` utiliza
**OpenRouter Batch API asíncrona**, no `POST /api/v1/chat/completions`.
El envío debe usar `POST /api/v1/batches` con el modelo base
`deepseek/deepseek-v4.1-flash-1017` (sin sufijo), y después consultar
`GET /api/v1/batches/{id}`.

Antes de enviar una solicitud real:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m diagnostico_openrouter_batch \
  --modelo deepseek/deepseek-v4.1-flash-1017:batch --solo-lectura
```

Esto solo comprueba la clave y el catálogo y no consume inferencia.

Para **enviar una sola solicitud ficticia facturable**, con autorización
explícita:

```bash
.venv/bin/python -m diagnostico_openrouter_batch \
  --modelo deepseek/deepseek-v4.1-flash-1017:batch \
  --permitir-pago --esperar 120
```

**Guarda el `batch_id` que se imprime inmediatamente después de crear el
lote.** Si sigue pendiente al terminar el tiempo de seguimiento, **no
repitas el comando de envío**, porque crearías otro lote facturable. Usa:

```bash
.venv/bin/python -m diagnostico_openrouter_batch \
  --consultar-batch batch_ID_DEVUELTO
```

Repite solo la consulta del mismo ID hasta obtener `completed`.
Puede tardar minutos u horas; el tiempo de respuesta no es adecuado para
el watchdog síncrono de PDFs de homcloud.

La interfaz web de homcloud **aún no implementa la ejecución asíncrona
batch**: bloquea los modelos `:batch` antes de extraer PDFs para evitar
el error HTTP 404 y consumos innecesarios de LLMWhisperer. Para producción
puedes usar el modelo base sin sufijo (API síncrona; precio diferente)
o desarrollar el procesamiento asíncrono completo.

La prueba real **puede consumir créditos** y solo envía el mensaje
ficticio «Responde solamente OK». OpenRouter informa que las entradas
y resultados de Batch API se conservan hasta 30 días o hasta su
eliminación; no uses documentos académicos reales en la prueba.

## Diagnóstico completo por terminal para HTTP 404

Una clave HTTP 200 en `GET /api/v1/key` **no demuestra** que el modelo
seleccionado tenga un endpoint de inferencia disponible. OpenRouter indica
que un modelo retirado o sin endpoints puede devolver HTTP 404.

En el Cloud Shell afectado:

```bash
cd ~/homcloud
git pull --ff-only origin main

# Elige el ID exacto del modelo que estás utilizando en la interfaz.
.venv/bin/python -m diagnostico_openrouter_terminal \
  --modelo openrouter/free --solo-lectura

# Una única inferencia con texto inventado, sin PDFs.
.venv/bin/python -m diagnostico_openrouter_terminal \
  --modelo openrouter/free --timeout 30
```

Para revisar un modelo diferente, sustituye `openrouter/free` por el
ID exacto del selector. Si es **de pago**, la lectura del catálogo
no cobra, pero para enviar una petición real debes añadir explícitamente
`--permitir-pago` (puede generar cargos).

El resultado incluye la autenticación, si el modelo existe en el
catálogo, el HTTP de consulta de endpoints, cuántos endpoints se
encontraron, el HTTP de la petición de inferencia y **solo el mensaje
de error sanitizado**. No imprime API key, encabezados, PDF ni
respuestas privadas; el prompt es únicamente «Responde solo OK.».
Si la API no devuelve JSON, el cuerpo del error no se muestra.

Revisa la salida antes de compartirla. Un modelo en el catálogo con
cero endpoints puede no estar disponible; un HTTP 404 cuando sí hay
endpoints requiere examinar el texto del error y restricciones de
privacidad o enrutamiento de la cuenta.

## Verificar en Cloud Shell

Cuenta auxiliar:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_openrouter_cliente test_integridad_app test_excel_runtime_patch -v
bash ./run_cloudshell.sh
```

Para infoclusiv, la ruta de la aplicación es `~/llmwhisperer-pdf-parser`; respalda primero cambios versionados locales antes de actualizar.

Documentación oficial:
- https://openrouter.ai/docs/api/api-reference/models/get-models
- https://openrouter.ai/docs/api/reference/overview
- https://openrouter.ai/settings/keys
