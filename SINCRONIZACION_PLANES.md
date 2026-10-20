# Sincronización de programas y planes entre Cloud Shell

**Fuente inicial obligatoria:** Cloud Shell **infoclusiv**. **Nunca** inicialices desde **auxiliarregistrocontrol**.

La rama prepara la aplicación, pero no crea un proyecto de Google Cloud ni modifica tu archivo local automáticamente. Al usar Firestore las dos instancias leen el mismo documento y guardan con control de revisión (evita sobrescribir una edición anterior). Si la conexión falla, la app no permite guardar datos antiguos como si fueran los oficiales.

## 1. Configurar el proyecto compartido en Google Cloud

Elige un proyecto Google Cloud que ambos usuarios/cuentas puedan acceder y habilita facturación únicamente si aceptas las condiciones del proyecto; revisa previamente cuotas y costes en la consola. Habilita la API Cloud Firestore y crea una base de datos **(default)** en modo **Firestore Native**, con una región definitiva. Puedes usar una instancia existente si cumple estas características. Asegúrate de que ambos usuarios tengan el rol IAM `roles/datastore.user` sobre ESE proyecto (o permisos mínimos equivalentes). Para crear la base de datos quizá se necesiten permisos administrativos separados. No es necesario hacer públicas las reglas de seguridad ni subir credenciales al repositorio.

Los comandos que siguen usan `TU_PROJECT_ID` como marcador: reemplázalo por el identificador real del proyecto compartido. No copies literalmente `TU_PROJECT_ID`.

## 2. En Cloud Shell principal **infoclusiv** (PRIMERO)

Antes de activar el modo nube, abre el homcloud ACTUAL de esta cuenta y verifica que sus planes sean los correctos. Guarda una última vez en su editor para que exista `settings/programas_planes.json`. Haz también un respaldo independiente del JSON:

```bash
cd ~/homcloud
mkdir -p ~/homcloud_respaldo
cp -av settings/programas_planes.json ~/homcloud_respaldo/programas_planes_infoclusiv_original.json
git pull --ff-only origin main
.venv/bin/python -m pip install -r requirements-sync.txt
gcloud auth application-default login
.venv/bin/python programas_planes_sync.py configurar --project TU_PROJECT_ID
.venv/bin/python programas_planes_sync.py inicializar --confirmar-origen-infoclusiv
.venv/bin/python programas_planes_sync.py estado
```

**ATENCIÓN:** El `git pull` anterior solo funcionará una vez fusionada la rama de sincronización en `main`; si todavía está en revisión, no ejecutes esta guía. El comando de inicialización solo crea la configuración central si NO existe: nunca reemplaza una configuración ya existente. El backup se guarda fuera del repositorio.

Para arrancar:
```bash
cd ~/homcloud && bash ./run_cloudshell.sh
```

## 3. En Cloud Shell secundario **auxiliarregistrocontrol** (DESPUÉS)

No ejecutes el comando `inicializar` aquí, incluso si el secundario tiene sus propios programas y planes:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m pip install -r requirements-sync.txt
gcloud auth application-default login
.venv/bin/python programas_planes_sync.py configurar --project TU_PROJECT_ID
.venv/bin/python programas_planes_sync.py estado
bash ./run_cloudshell.sh
```

El comando `estado` debe indicar Firestore y mostrar los programas ya publicados desde **infoclusiv**. Si indica que no hay documento, se debe corregir la conexión; **no inicialices con los datos del secundario**.

## 4. Operación habitual

- Ambos Cloud Shell consultan Firestore al ejecutar Streamlit.
- Cualquier cuenta con acceso podrá editar y guardar en la misma base.
- Si otra cuenta guardó mientras estabas editando, la app rechaza la escritura antigua.
- Usa **Recargar programas desde la nube** para descartar cambios locales del editor y leer la nueva versión.
- Los historiales de versiones remotas se conservan en `homcloud_config/programas_planes/historial` y los respaldos locales en `settings/backups/`, todos excluidos de Git. No son un sustituto de un respaldo externo de larga duración.
- Si Firestore no está disponible, la aplicación muestra un error y bloquea guardados: no vuelve silenciosamente al JSON local.
- Si no se ha configurado Firestore, homcloud continúa en modo local sin afectar el funcionamiento previo.

## 5. Seguridad y mantenimiento

- `settings/cloud_sync.json` contiene solo el ID del proyecto, no claves; no lo subas a Git.
- La autenticación local usa Application Default Credentials y autorizaciones IAM. No subas claves JSON de cuentas de servicio.
- Revisa cuota y costes de Firestore periódicamente. El acceso de la interfaz lee el catálogo en cada ejecución de Streamlit.
- No elimines `settings/programas_planes.json` ni su copia de respaldo hasta haber confirmado que ambas instancias usan el mismo contenido.
