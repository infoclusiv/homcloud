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

**Importante:** si tu archivo privado `.env` contiene `OPENROUTER_API_KEY`, esa variable tiene prioridad sobre el archivo nuevo. Las dos cuentas de Cloud Shell tienen entornos independientes, por lo que cada una guarda su propia clave una vez.

Crea tus credenciales en https://openrouter.ai/settings/keys. No compartas claves ni archivos de respaldo que las contengan.

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
