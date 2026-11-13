# ChatGPT OAuth como tercer proveedor (EXPERIMENTAL / NO PRODUCCION)

Este cambio está en una rama de prueba separada de main. **No es
autorización para procesar actas reales**. Los PDFs quedan desactivados
por defecto para ChatGPT OAuth, y DeepSeek/OpenRouter sigue siendo el
predeterminado.

## Evidencia previa

Pruebas aisladas en Cloud Shell (2026-11-12, sesión personal del dueño):

- PoC OAuth: HTTP 200 y response.completed con GPT-6.1 Sol.
- Renovación de token real: exitosa y con bloqueo concurrente.
- Versión 4: 30 tests offline correctos; dos casos preliminares de
  pregrado correctos; batería de 5 casos con resultado correcto (incluye
  pregrado normal, sufijo F, 2024, posgrado y nota baja).
- Pruebas sintéticas != validación del mundo real. No aseguran exactitud
  ni ausencia de alucinaciones en actas reales.

## Uso de la rama

No hagas checkout de esta rama en el entorno de producción mientras
proceses un lote. Usa un clon de prueba separado de ~/homcloud o revisa
la PR primero; no borres datos, .env, sesiones ni preferencias.

La cuenta de Cloud Shell debe contar con su propia autorización OAuth.
El cliente usa exclusivamente
~/.config/homcloud-siwc-poc/oauth_session.json (credencial fuera de Git).
Reutiliza el flujo de login local en Windows y transferencia privada
probado en la PoC. **Nunca subas oauth_session.json a GitHub, chats,
firestore o archivos públicos.**

Al seleccionar ChatGPT OAuth en la interfaz experimental:
1. Consulta los modelos de tu plan.
2. Selecciona un modelo de los devueltos (por ejemplo gpt-6.1-sol).
3. Pulsa «Probar ChatGPT OAuth con texto ficticio».

La prueba envía texto inventado y valida un pequeño objeto JSON sin
LLMWhisperer. No subas actas reales en esta fase.

## Protección de producción

Con ChatGPT OAuth seleccionado:
- Los botones que procesan PDFs quedan deshabilitados.
- Una segunda barrera en ejecutar_lote_streamlit detiene la tanda ANTES
  de gastar solicitudes LLMWhisperer.
- Una variable de entorno específica HOMCLOUD_CHATGPT_OAUTH_ACTAS=1
  existe para habilitación posterior. NO establecerla hasta comprobar
  por separado elegibilidad del despliegue, permisos institucionales y
  los límites reales de uso y retención de datos.
- Para pruebas con ChatGPT OAuth, se limita a un worker; el refresh
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

1. CI y prueba de interfaz sobre esta rama en un clon separado.
2. Revisión de permisos de acceso a la interfaz de Cloud Shell.
3. Elegibilidad remota y privacidad institucional.
4. Medición repetida de calidad de JSON/AHK en muestra anonimizada
   con resultados de referencia confiables.
5. Tolerancia a 401/403/429, rate limiting y expiración de sesión.
6. Revisión humana de cualquier AHK antes de ejecutarlo en Banner.
