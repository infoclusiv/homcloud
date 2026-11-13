# ChatGPT OAuth como tercer proveedor (ACTIVACIÓN CONTROLADA)

El procesamiento de actas reales **permanece deshabilitado por defecto**.
Solo se habilita individualmente en un Cloud Shell después de verificar
autorización institucional, elegibilidad de la integración, la sesión
OAuth y el catálogo del modelo. La barrera previa a LLMWhisperer falla
en modo seguro cuando falta cualquiera de los controles. DeepSeek/OpenRouter
continúan como predeterminados y conservan su funcionamiento.

## Evidencia previa

Pruebas aisladas en Cloud Shell (2026-11-12, sesión personal del dueño):

- PoC OAuth: HTTP 200 y response.completed con GPT-6.1 Sol.
- Renovación de token real: exitosa y con bloqueo concurrente.
- Versión 4: 30 tests offline correctos; dos casos preliminares de
  pregrado correctos; batería de 5 casos con resultado correcto (incluye
  pregrado normal, sufijo F, 2024, posgrado y nota baja).
- Pruebas sintéticas != validación del mundo real. No aseguran exactitud
  ni ausencia de alucinaciones en actas reales.

## Despliegue y credenciales

Actualiza la rama principal mediante `git pull --ff-only origin main`
solo cuando no haya lotes en ejecución. Conserva credenciales, datos,
preferencias, `.env`, `uploads/` y `outputs/` locales.

La cuenta de Cloud Shell debe contar con su propia autorización OAuth.
El cliente usa exclusivamente
~/.config/homcloud-siwc-poc/oauth_session.json (credencial fuera de Git).
Reutiliza el flujo de login local en Windows y transferencia privada
probado en la PoC. **Nunca subas oauth_session.json a GitHub, chats,
firestore o archivos públicos.**

Al seleccionar ChatGPT OAuth en la interfaz experimental:
1. Consulta los modelos de tu plan.
2. Selecciona un modelo de los devueltos (por ejemplo gpt-6.1-sol).
3. Elige el nivel de razonamiento (Automático, Low, Medium, High, Extra High o Máximo).
   Al cambiarlo, se guarda de forma atómica en
   `settings/razonamiento_chatgpt_oauth.txt` (0600, excluido de Git).
   Se recupera al volver a iniciar Homcloud en el mismo Cloud Shell.
   Esta preferencia es independiente del motor DeepSeek predeterminado,
   no se comparte mediante Firestore ni altera la cuenta de ChatGPT.
4. Pulsa «Probar ChatGPT OAuth con texto ficticio».

El nivel `auto` omite `reasoning` y conserva el comportamiento previo.
Los niveles explícitos usan `reasoning: {"effort": "..."}`. GPT-6.1 Sol
admite `low`, `medium`, `high`, `xhigh` y `max`; la compatibilidad de
otros modelos puede variar. Si el servidor rechaza un nivel, se muestra el
error sin degradar el razonamiento silenciosamente ni reintentar.
La prueba sintética permite verificar cada nivel con texto ficticio,
sin enviar documentos reales. La aceptación de cada nivel por el
servicio OAuth del plan todavía requiere verificación en Cloud Shell.

La prueba envía texto inventado y valida un pequeño objeto JSON sin
LLMWhisperer. No subas actas reales en esta fase.

## Protección de producción

Con ChatGPT OAuth seleccionado:
- Sin autorización local por host, los botones de PDF y reintentos se
  deshabilitan; el preflight detiene la tanda ANTES de LLMWhisperer.
- La activación local exige confirmación interactiva de las condiciones
  institucionales y la elegibilidad, y se vincula a sesión y host.
- Nunca basta una variable de entorno para habilitar las actas en masa.
- Todos los lotes ChatGPT OAuth se limitan a un worker; el refresh
  token se renueva con flock y reemplazo atómico.
- El token y los mensajes HTTP nunca se copian al CSV o Firestore. Los
  textos de origen y resultados siguen sujetos a las reglas normales
  de retención local de homcloud.
- Si no hay sesión válida, se detiene con un error descriptivo.
- OpenRouter/OpenCode permanecen operativos. No se cambia el valor
  inicial DeepSeek V4 Flash.

## Contrato técnico

El motor recibe texto plano ya extraído del PDF y el mismo contrato
JSON que usa homcloud. Envía por Responses API con:
- POST https://api.openai.com/v1/responses
- store=false
- stream=true
- instructions con contrato JSON existente
- input con el TXT (sin enviar el PDF)
- espera obligatoria a response.completed
- sin uso de OPENAI_API_KEY ni claves de OpenRouter

El nombre del modelo debe ser un slug del catálogo de la cuenta.
No usa ChatGPT backend-api ni APIs internas.

## Requisitos de cumplimiento

La documentación actual distingue herramientas locales personales o
open-source con VM autogestionada frente a aplicaciones de pago o
alojadas remotamente que se ofrecen a terceros. Confirmar el caso de
uso de homcloud y autorización de tratamiento de datos académicos
antes de habilitar el procesamiento en la interfaz web.

Fuentes:
- https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt

## Pruebas sin API ni credenciales

python -m unittest test_chatgpt_oauth_cliente test_integridad_app -v

El botón de la UI crea un TXT ficticio y ejecuta una sola inferencia,
que consume cuota del plan. No hay ejecución de fondo ni autopago
mediante API key.

## Pendiente de validar antes de producción

1. CI y prueba de interfaz: validadas con casos ficticios antes de integrar.
2. Confirmar que el acceso a Cloud Shell Web Preview continúa restringido a
   la cuenta autenticada y que no se publica por otros medios.
3. Elegibilidad remota y privacidad institucional antes de cualquier acta real.
4. Medición repetida de calidad de JSON/AHK en muestra anonimizada
   con resultados de referencia confiables.
5. Tolerancia a 401/403/429, rate limiting y expiración de sesión.
6. Revisión humana de cualquier AHK antes de ejecutarlo en Banner.

## Activación individual y consciente

El proveedor puede procesar PDFs reales solo si el administrador confirma
en la terminal de CADA Cloud Shell el tratamiento institucional permitido
y la elegibilidad del despliegue mediante:
`python -m chatgpt_oauth_activacion habilitar`.

El interruptor local se vincula a la identidad OAuth y al identificador
estable del host; no hay variable de entorno que habilite todo globalmente.
Ausencia de autorización, corrupción, permisos incorrectos, cambio de
identidad o modelo indisponible bloquean la tanda antes de llamar a
LLMWhisperer. Los reintentos respetan la misma barrera.
Para revocar: `python -m chatgpt_oauth_activacion deshabilitar`.

La declaración local no demuestra que una institución haya concedido
autorización: antes de activarla debe existir dicha aprobación verificable.
El procesamiento con terceros incluye LLMWhisperer y OpenAI, y continúa
sujeto a políticas de retención, confidencialidad y revisión de resultados.
