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
