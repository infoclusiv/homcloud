# OpenRouter en homcloud — modelos gratuitos seleccionables desde la web

Homcloud permite **OpenCode CLI o OpenRouter API directa**. La segunda opción
no requiere instalar OpenCode: utiliza las mismas funciones LLMWhisperer,
prompts de Pregrado/Posgrado, contrato de JSON, validaciones académicas,
generación AHK con Python, descargas CSV/ZIP e historial de Firestore.

## Primer uso

1. Crea una API key en **https://openrouter.ai/settings/keys**.
   No la compartas con nadie ni la incluyas en GitHub.
2. En el Cloud Shell elegido, actualiza el repositorio:
   ```bash
   cd ~/homcloud       # En infoclusiv usa ~/llmwhisperer-pdf-parser
   git pull --ff-only origin main
   .venv/bin/python -m unittest test_openrouter_cliente test_integridad_app -v
   bash ./run_cloudshell.sh
   ```
3. Abre Web Preview, entra a **Configuración rápida → Proveedor de IA**
   y selecciona **OpenRouter**.
4. En **API key de OpenRouter**, pega tu clave (campo tipo contraseña).
   Se usa **solo en esa sesión de Streamlit**: no se escribe en archivos,
   Firestore, CSV ni en mensajes de error. Si reinicias la sesión,
   vuelve a introducirla.
5. En **Modelo OpenRouter** elige uno del menú. Puedes filtrar por nombre
   o actualizar el catálogo. Hay una opción `openrouter/free` que permite
   al proveedor escoger un modelo gratuito de la lista disponible.
6. Lee la advertencia de privacidad y activa la casilla de autorización
   solo si tienes permiso para enviar las actas al proveedor.
7. Prueba primero **1 PDF** y **1 proceso simultáneo** antes de usar lotes.

## Opción para API key persistente por cuenta

En vez de pegar la clave cada sesión, puedes guardarla **en el archivo .env
privado de ese Cloud Shell** bajo el nombre:

```text
OPENROUTER_API_KEY=tu_clave_privada
```

Recomendamos protegerlo con `chmod 600 .env`. El archivo está ignorado
por Git. Debes configurarlo por separado en cada Cloud Shell. Nunca publiques
la clave en el catálogo compartido o Firestore.

Para probar la conexión de forma sintética desde terminal, sin PDFs:

```bash
cd ~/homcloud
.venv/bin/python -m openrouter_cliente probar --model openrouter/free --timeout 45
```

El comando consume **una solicitud real de cuota gratuita** y solo envía
un texto ficticio. Si la conexión funciona pero el modelo no genera el JSON
esperado, `conexion_ok` puede ser verdadero y `json_valido` falso;
en ese caso, elige otro modelo gratuito.

## Selección, persistencia y seguridad

La lista se obtiene del endpoint público de modelos de OpenRouter;
homcloud solo permite los IDs de variantes terminadas en `:free` y
`openrouter/free`. **Rechaza modelos de pago antes de realizar la solicitud.**
El selector ofrece también un campo manual para un ID `:free` válido.

La selección se conserva en la sesión. Cuando no hay un modelo global
publicado, se guarda también el modelo elegido en la configuración local.
Puedes utilizar **Publicar este modelo globalmente** para aplicar la
selección a las dos cuentas mediante el sistema Firestore existente.
**Solo el identificador de modelo** se comparte globalmente: nunca la clave.

El cliente usa HTTPS y `/api/v1/chat/completions`; envía el contrato
técnico JSON y el TXT extraído por LLMWhisperer. La respuesta vuelve
al mismo validador que ya genera AHK/CSV. Los archivos de respuesta
locales se borran bajo el ciclo de retención de lotes anterior.

El proveedor remoto recibe contenido de actas académicas, que puede incluir
datos personales. Antes de enviar documentos reales, revisa la autorización
institucional, condiciones de privacidad y retención del modelo elegido.
`openrouter/free` puede cambiar dinámicamente de proveedor; usa un
modelo específico si necesitas revisar sus condiciones.

## Cuotas y límites

OpenRouter indica para el nivel sin compra de créditos un límite típico de
**50 solicitudes/día y 20/minuto** en variantes gratuitas. Los intentos
fallidos pueden consumir cuota. El procesamiento limita la ejecución a
**2 solicitudes OpenRouter simultáneas**, aunque el deslizador general
indique más workers. No hay garantía de disponibilidad continua ni de
capacidad ilimitada. No cambia automáticamente a modelos de pago ni
intenta sobrepasar bloqueos 429.

El cliente muestra errores seguros por categoría:
- **HTTP 401:** clave incorrecta o no autorizada.
- **HTTP 402/403:** restricciones de saldo, cuenta o acceso.
- **HTTP 429:** cuota o límite de velocidad.
- **HTTP 5xx:** problemas del proveedor.
- **Timeout / JSON vacío o inválido:** revisar modelo elegido y contrato.

El timeout interno de la llamada OpenRouter se ajusta al tiempo restante
del PDF con un margen de seguridad. A diferencia de la CLI, una petición
HTTPS bloqueada no se puede terminar desde otro hilo: el timeout de red
es el límite de espera real, por lo que no conviene configurarlo por encima
del timeout total del PDF.

## Compatibilidad

Los modelos OpenCode previamente seleccionados continúan funcionando.
Los nombres de carpetas/archivos técnicos `*_opencode.json` se mantienen
para que los mecanismos anteriores de recuperación y descarga no fallen,
aunque el proveedor elegido ahora sea OpenRouter.

Documentación oficial:
- Modelos: https://openrouter.ai/docs/api/api-reference/models/get-models
- API: https://openrouter.ai/docs/api/reference/overview
- Modelos gratuitos: https://openrouter.ai/collections/free-models
- Claves API: https://openrouter.ai/settings/keys
