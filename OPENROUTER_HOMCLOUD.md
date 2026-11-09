# OpenRouter en homcloud — modelos gratuitos y de pago

## Configuración desde la interfaz

1. Actualiza el repositorio en tu Cloud Shell y abre la aplicación.
2. En **Proveedor de IA** selecciona **OpenRouter**.
3. En **🔑 Configurar API key OpenRouter**, pega la clave una sola vez y pulsa **Guardar API key permanentemente en este Cloud Shell**.
4. En **Catálogo**, elige **Todos**, **Gratis** o **Pago**.
5. Busca por nombre o ID y selecciona **Modelo OpenRouter**. Usa **Actualizar catálogo completo** cuando necesites refrescar los precios y los modelos.
6. Si es de pago, revisa el precio y marca **Autorizo el uso facturable de [modelo]**.
7. Pulsa **Probar modelo con texto ficticio** antes de subir archivos reales.
8. Revisa privacidad y autorización institucional. Empieza con un PDF y un worker.

El catálogo procede del endpoint oficial `GET /api/v1/models`; permite TODOS los modelos compatibles con texto, no solamente `:free`. Muestra precios USD por millón de tokens de entrada y salida cuando están disponibles; esos precios no son un techo de gasto. Los modelos pagos pueden consumir créditos incluso en pruebas sintéticas; la autorización se solicita para cada modelo por separado.

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

## Interfaz más compacta

En Inicio se conservan solamente los controles de trabajo diario: concurrencia, proveedor/modelo, carga de PDFs o Excel, progreso, resumen, errores, reintentos y descargas.

El sidebar añade las páginas:
- **Programas y planes**: editor completo y gestión del catálogo.
- **Configuración operativa**: predeterminados globales, retención y limpieza manual.

Las opciones de sincronización, prompts, timeouts y publicación global del modelo quedan en desplegables del sidebar. Esto evita que un editor de programas colapsado deje un gran espacio vacío al lado de un bloque de configuración mucho más alto.

## Integración y privacidad

Con OpenRouter seleccionado se mantiene el flujo de LLMWhisperer → TXT → contrato JSON → validación Python → AHK + CSV + historial. Los modelos de pago requieren autorización explícita antes del procesamiento y de los reintentos. La interfaz limita de forma conservadora a 2 las llamadas simultáneas a OpenRouter.

Los TXT incluyen potencialmente datos personales académicos y serán transmitidos a OpenRouter y al proveedor seleccionado. Verifica la política institucional, las condiciones de retención de cada proveedor, la privacidad del modelo concreto y la autorización antes de enviar documentos reales.

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
