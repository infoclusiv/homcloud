# homcloud en dos o mas cuentas de Google Cloud Shell

El repositorio es compartido; el entorno de cada cuenta es independiente.
No se fija el nombre de usuario, la ruta /home ni el dominio de una cuenta.
Este iniciador esta destinado a ejecutarse exclusivamente en sesiones autenticadas de Google Cloud Shell.
No uses este script para desplegar servicios web publicos, porque desactiva las protecciones CORS/XSRF.

## Iniciar la web app en cada cuenta

En la terminal de **cada** cuenta, desde la carpeta donde clonaste homcloud:

```bash
git pull --ff-only origin main
bash ./run_cloudshell.sh
```

Abre **Web Preview > Preview on port 8080**. El script muestra la URL personalizada solo si `WEB_HOST` esta disponible.
Esa variable es opcional: si no existe, usa el menu **Web Preview > Preview on port 8080**.
No hace falta configurar `WEB_HOST`.

Puedes utilizar simultaneamente el puerto 8080 en ambas cuentas: cada cuenta
dispone de su propia maquina y sus propios procesos.

El script entra automaticamente en la carpeta donde reside, utiliza
`.venv/bin/python` cuando exista y detiene una instancia anterior de
**homcloud en esa misma carpeta** que estuviera usando el puerto.
No detiene aplicaciones ajenas ni procesos de otra cuenta.

Si necesitas usar otro puerto por una razon especifica:

```bash
HOMCLOUD_PORT=8501 bash ./run_cloudshell.sh
```

No es necesario cambiar el puerto desde el menu de Cloud Shell en el uso habitual.
La vista previa vuelve a mostrar 8080 al reabrir Cloud Shell, por lo que
este es el valor predeterminado del script.

**Nota:** el script inicia la aplicacion cuando lo ejecutas. No configura
inicio automatico de procesos cuando Cloud Shell se reinicia.

Deten la app con **Ctrl+C**.

## Configuracion independiente

Cada cuenta debe mantener de forma local sus propias dependencias en `.venv/`
y credenciales en `.env` o `.streamlit/secrets.toml` cuando sean necesarias.
Esas rutas estan excluidas del repositorio mediante `.gitignore`.
No subas claves ni tokens a GitHub. Las carpetas `uploads/` y `outputs/`
tambien son locales y estan ignoradas.

## Por que funciona el Web Preview

Google documenta que el proxy HTTPS de Cloud Shell requiere iniciar Streamlit
con estos argumentos:

```text
--browser.serverAddress=localhost
--server.enableCORS=false
--server.enableXsrfProtection=false
```

Se usan unicamente en `run_cloudshell.sh`; no se cambian los valores globales
de `.streamlit/config.toml`. Fuera de la vista previa autenticada de
Google Cloud Shell, conserva activadas las protecciones CORS y XSRF.

Referencia: https://docs.cloud.google.com/shell/docs/using-web-preview

## OpenRouter: catálogo completo, modelos de pago y clave persistente

Consulta [OPENROUTER_HOMCLOUD.md](OPENROUTER_HOMCLOUD.md) para usar el
catálogo completo de modelos, con filtros Gratis/Pago, precios orientativos
y aprobación antes de enviar solicitudes a modelos facturables. La API key
se introduce una sola vez y se guarda de forma privada en
`settings/openrouter_api_key.txt` (ignorado por Git y con permisos 0600).
El sidebar ahora incluye el editor independiente de programas/planes y
la configuración operativa; el procesamiento diario queda compacto en Inicio.

## Diagnosticar bloqueos de OpenCode

Si una tanda llega a «OpenCode CLI» y nunca continúa, consulta
[DIAGNOSTICO_OPENCODE.md](DIAGNOSTICO_OPENCODE.md). Incluye una prueba
sin PDFs de estudiantes, un resumen privado de logs antiguos, cancelación
del proceso OpenCode al vencer el timeout del lote y una nueva página
«Diagnóstico OpenCode» en Streamlit. Antes de reintentar una tanda grande,
prueba el modelo con 1 archivo y concurrencia de 1.

## Configuración operativa global

Para compartir los prompts de Pregrado/Posgrado, modelo OpenCode, timeouts, concurrencia y retención, consulta [PREFERENCIAS_Y_RETENCION.md](PREFERENCIAS_Y_RETENCION.md). La publicación inicial de prompts/modelo/timeouts es manual; los archivos locales no se sobrescriben, y cada cuenta puede mantener excepciones locales. Ejecuta `python -m unittest test_configuracion_global test_operativa_compartida test_recuperacion_lotes test_integridad_app -v` tras actualizar el repositorio.

## ChatGPT OAuth en la interfaz principal (prueba ficticia y activación controlada)

El proveedor aparece en el puerto 8080 sin alterar DeepSeek/OpenRouter.
Por defecto solo admite pruebas ficticias; los PDFs reales requieren
activación por Cloud Shell y autorización institucional previa.

- Se usa la sesión privada de la MISMA cuenta Cloud Shell que ejecuta
  la app: `~/.config/homcloud-siwc-poc/oauth_session.json` (jamás en Git).
- El selector de esfuerzo OAuth se guarda solo en
  `settings/razonamiento_chatgpt_oauth.txt`; es independiente de la
  preferencia del proveedor y de Firestore.
- Las pruebas de inferencia únicamente envían texto ficticio.
- Sin autorización local válida, los PDFs con ChatGPT OAuth quedan bloqueados
  antes de LLMWhisperer, incluidos los reintentos. No existe variable de
  entorno que habilite globalmente todas las cuentas. La habilitación requiere
  `python -m chatgpt_oauth_activacion habilitar` por instancia.
- Para usarlo desde el puerto principal, actualiza `main` después de que
  las pruebas hayan aprobado, e inicia `bash ./run_cloudshell.sh` desde
  tu CLON PRINCIPAL; el clon experimental en otro puerto queda independiente.
- El estado de la sesión y el nivel de razonamiento no se copian por Git.
  El archivo de preferencias de razonamiento puede trasladarse manualmente
  entre clones del MISMO Cloud Shell si se desea mantener el nivel.
- El botón de prueba sintética nunca usa documentos académicos reales.
  El flujo de PDFs requiere evaluación separada de elegibilidad y privacidad.

Consulta `CHATGPT_OAUTH_EXPERIMENTAL.md` para detalles y limitaciones.

## Habilitación controlada de actas reales con ChatGPT OAuth

**No se activa de forma automática al actualizar Git.** Cada Cloud Shell
requiere una sesión OAuth propia y una declaración local explícita, tras
confirmar que existen permisos institucionales para enviar datos académicos
a LLMWhisperer y a OpenAI, así como que el despliegue cumple con SIWC.

Comandos dentro del clon principal de CADA cuenta, con OAuth ya importado:

```bash
cd ~/homcloud
.venv/bin/python -m chatgpt_oauth_activacion estado
.venv/bin/python -m chatgpt_oauth_activacion habilitar
.venv/bin/python -m chatgpt_oauth_activacion estado
```

En infoclusiv el clon principal suele estar en
`~/llmwhisperer-pdf-parser` y no en `~/homcloud`.

La habilitación requiere escribir exactamente la frase solicitada,
y se guarda en `settings/chatgpt_oauth_actas_autorizado.json` con permisos
0600 y una huella no reversible de sesión/host. No contiene contraseñas,
tokens ni datos académicos. La preferencia no se sube a GitHub, no se
comparte entre Cloud Shell y se invalida al cambiar de sesión/host.

Para REVOCAR inmediatamente en una cuenta:

```bash
.venv/bin/python -m chatgpt_oauth_activacion deshabilitar
```

Preflight: si falta autorización, sesión o el modelo no existe en el
catálogo del plan, el procesamiento se detiene ANTES de LLMWhisperer.
La concurrencia OAuth continúa limitada a un worker. Los AHK deben
inspeccionarse manualmente antes de ejecutarlos en Banner. Prueba
primero con un único documento autorizado, con resultado de referencia.

La confirmación técnica del operador NO sustituye la autorización
formal de la institución ni determina por sí sola la elegibilidad
de Sign in with ChatGPT. No activar si cualquiera de ellas falta.

## Autorizar OAuth en otra cuenta: ejemplo infoclusiv

En el Cloud Shell de `infoclusiv` (con `main` actualizado), preparar
una identidad estable de HOST antes de realizar el nuevo login local:

```bash
cd ~/llmwhisperer-pdf-parser
.venv/bin/python -m chatgpt_oauth_activacion preparar-host
```

El valor impreso de `HOST_ID` debe comenzar por `urn:uuid:` (formato
requerido por `siwc_poc.py`). **No es un token ni una contraseña.**
Las versiones anteriores de Homcloud generaban por error solo el UUID
sin ese prefijo. Repetir `preparar-host` lo corrige sin cambiar el UUID
únicamente cuando todavía no hay sesión OAuth ni autorización local;
nunca sobrescribe una identidad ya asociada a credenciales.

Cópialo al archivo `host_id.txt` del perfil AISLADO de la PoC
Windows, dentro de `.config/homcloud-siwc-poc/`, antes de ejecutar
`siwc_poc.py login`. Usa una configuración local distinta a la usada
para `auxiliarregistroycontrol24`; no reutilices ni sobrescribas su
`oauth_session.json`.

Una vez completado `login` en Windows, sube únicamente el nuevo
`oauth_session.json` mediante **Cloud Shell > Más > Subir archivo**
abierto en la sesión Google de infoclusiv. El archivo aparecerá como
`~/oauth_session.json` en el Shell; evita subirlo al repositorio.

Ejecuta en Cloud Shell (solo para una instalación NUEVA, sin sesión previa):

```bash
umask 077
install -d -m 700 ~/.config/homcloud-siwc-poc
test -s ~/oauth_session.json || { echo "No se cargó la sesión privada"; exit 1; }
test ! -e ~/.config/homcloud-siwc-poc/oauth_session.json || {
  echo "Ya hay una sesión: no se sobrescribió"; exit 1;
}
install -m 600 ~/oauth_session.json ~/.config/homcloud-siwc-poc/oauth_session.json
rm -f ~/oauth_session.json
.venv/bin/python - <<'PY'
from chatgpt_oauth_cliente import estado_chatgpt_oauth, listar_modelos_chatgpt_oauth
status = estado_chatgpt_oauth()
print("SESION_OK:", status.get("ok"))
if status.get("ok"):
    catalogo = listar_modelos_chatgpt_oauth()
    print("CATALOGO_OK:", catalogo.get("ok"))
    print("NUM_MODELOS:", len(catalogo.get("models") or []))
PY
```

Jamás compartas el contenido del archivo OAuth ni imprimas los tokens.
Si se cambia de cuenta ChatGPT o de host, la autorización local de actas
se invalida automáticamente y hay que revisar la configuración.
