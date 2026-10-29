# Preferencias globales, descargas y recuperación de homcloud

## Historial permanente y borrado automático de PDFs y temporales

**Nueva política predeterminada:** los archivos de cada lote se conservan **3 días**. Al abrir o usar homcloud, el mantenimiento automático comprueba si hay lotes antiguos; en la app se revisa como máximo cada 12 horas. También se puede configurar otro plazo de 1 a 90 días en **Configuración operativa → Eliminar archivos de lotes después de (días)**. Esta preferencia está compartida en Firestore y no altera la retención manual anterior. Si Cloud Shell está apagado, NO hay un proceso que ejecute limpieza en segundo plano: se realiza al volver a usar la aplicación.

Antes de borrar `uploads/<id>` y `outputs/runs/<id>`, se archiva cada fila del CSV final o parcial en **Firestore compartido** (`homcloud_historial_registros`, un documento por lote y PDF), y en el CSV compacto local `historial/homologaciones_historico.csv`. El CSV se excluye de Git. La tabla histórica conserva fecha, lote, cuenta, nombre de archivo, nivel, prompt, programa origen, programa destino, plan, créditos homologados, estado, duración, modelo y una descripción acotada del error. **No conserva PDFs, carpetas de workers, AHK ni respuestas OpenCode completas**. Los reintentos se registran con su propio identificador de lote para poder auditar cada intento.

Los PDFs que todavía no tienen fila de resultado se archivan como `Error no iniciado` antes de borrar sus originales. Los lotes en ejecución se protegen con su marcador; una marca de un proceso terminado no impide la limpieza al reabrir la aplicación. Si falla Firestore, la lectura del CSV, el guardado del respaldo local o cualquier paso de archivado, **no se borra el lote**. Se reintenta en la siguiente ejecución. La limpieza también retira publicaciones antiguas bajo `static/pdfs`, que pueden mantener ocupado el disco incluso después de eliminar `uploads` debido a los hardlinks.

**Historial de homologaciones:** abre esta página desde el menú lateral, pulsa **Consultar historial completo** y utiliza el buscador o filtro de Estado. Puedes descargar el histórico **completo** o **filtrado** a CSV, con los resultados reunidos desde ambos Cloud Shell cuando usan el mismo proyecto Firestore. Antes de borrar resultados anteriores existentes, pulsa **Importar lotes disponibles** para migrarlos; esto no borra archivos. Para ejecuciones nuevas, el archivo se actualiza al finalizar el lote o reintento. El histórico es por intento, por lo que un PDF puede tener varios registros si fue reintentado.

En la terminal, puedes usar estos comandos opcionales en cada instalación:

```bash
cd ~/homcloud
.venv/bin/python -m historial_homologaciones estado
.venv/bin/python -m historial_homologaciones importar
# Solo si deseas ejecutar la limpieza manual antes del mantenimiento automático:
.venv/bin/python -m historial_homologaciones limpiar --dias 3
```

**Importante sobre datos personales:** los nombres de archivos pueden contener nombres de estudiantes. Este historial almacena esos campos en Firestore y en un CSV local. Restringe permisos del proyecto, no compartas CSV sin autorización y revisa la política institucional de conservación de registros. "Permanente" significa que no aplica la limpieza automática de tres días; no sustituye una política formal de respaldos ni una garantía de conservación indefinida.

**Verificación sin borrar archivos de producción:**

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_historial_homologaciones test_configuracion_global test_integridad_app -v
bash ./run_cloudshell.sh
```

## Configuración compartida entre Cloud Shell

Las dos cuentas utilizan el mismo Firestore que ya sincroniza programas y planes.
El documento independiente `homcloud_config/preferencias_operativas` conserva:
- `procesos_predeterminados` (1–20; si aún no hay valor guardado, 4).
- `retencion_dias` (1–90; valor inicial 7).

En **Configuración operativa**, cambia el deslizador y pulsa **Guardar predeterminado global**. El segundo Cloud Shell puede pulsar **Recargar predeterminado**, o abrir una nueva sesión. Las escrituras verifican la revisión: una edición antigua no sobreescribe cambios remotos sin avisar.

Sin proyecto Firestore configurado, las preferencias se guardan localmente en `settings/operacion_global.json` (excluido de Git). Si Firestore está configurado pero falla, no se guarda localmente como si fuera un dato global.

**Importante:** el límite de concurrencia se aplica **por Cloud Shell**. Dos instancias con 10 procesos cada una pueden ejecutar hasta 20 workers combinados; no hay un semáforo compartido de cuotas de OpenCode/LLMWhisperer.

## Distribución del resumen final y columna Plan

La tabla **Resumen final** abre con este orden (tomado de la vista solicitada):
**Archivo → Prompt usado → Programa origen → Programa al que aspira → Plan → Nivel → Estado → Error → Créditos homologados**, seguido de las columnas técnicas.

Los dos programas tienen anchuras limitadas (205 y 240 px), y el archivo tiene 245 px. Esto evita que textos extremadamente largos oculten *Plan* detrás de varios desplazamientos horizontales. Los nombres completos se conservan en los datos y CSV; se trata solo de una preferencia de visualización.

Para personalizarlo abre **⚙️ Personalizar el orden de las columnas** encima del resultado, selecciona la columna y pulsa **←**, **→** o **Al inicio**. Cada clic **guarda inmediatamente** el nuevo orden. También hay un botón **Restablecer distribución recomendada**. Las siguientes tandas, las vistas de resultados recuperados dentro de la app y la otra cuenta de Cloud Shell utilizan esa disposición.

Se guarda en Firestore bajo `homcloud_config/columnas_resumen` si ambos Cloud Shell están conectados al mismo proyecto. Se detectan conflictos cuando otra sesión guarda antes. Sin Firestore se guarda en `settings/columnas_resumen.json` y **solo** vale en ese Cloud Shell. Ni los prompts ni la concurrencia ni los CSV cambian cuando mueves una columna.

**Limitación de Streamlit:** arrastrar una columna directamente en la tabla modifica la disposición momentánea del navegador, pero Streamlit no expone ese gesto al código Python para persistirlo. **Para conservar el orden usa el panel de flechas.**

Prueba rápida después de actualizar:

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_configuracion_tabla test_integridad_app -v
bash ./run_cloudshell.sh
```

## Descargas sin esperar a terminar

Abre homcloud y, desde el menú lateral, entra a **Recuperar resultados**. Puedes abrir esa página en **otra pestaña** y mantener el procesamiento activo en la original. En la pestaña de recuperación:
1. Pulsa **Actualizar lotes y resultados** después de que termine cada PDF.
2. Selecciona el lote más reciente (o uno anterior).
3. Descarga **CSV recuperado** o **ZIP de AHK recuperados** en cualquier momento.

La página reconstruye las filas en memoria, combinando reintentos con resultados previos. Si falta un resultado pero el PDF original sigue en `uploads/<run_id>/`, se marca `Error no iniciado` para poder reintentar. No requiere que el procesamiento finalice. Las descargas del CSV y ZIP se hacen mediante widgets de Streamlit, sin crear copias nuevas en `static/exports`. Los originales PDF vuelven a poder abrirse haciendo clic en el nombre del archivo de la tabla.

**Columna Archivo:** los nombres vuelven a ser enlaces clicables (`LinkColumn`) que abren el PDF original en otra pestaña. El visor estático queda habilitado exclusivamente para recuperar el comportamiento anterior. Cada PDF se publica en `static/pdfs/<token>/<nombre>.pdf` bajo una URL generada con HMAC y un secreto exclusivo del Cloud Shell (`settings/.pdf_link_secret`, ignorado por Git). En el mismo sistema de archivos se crea un **hard link**: las dos rutas apuntan a los mismos bytes, sin duplicarlos. Si el filesystem no admite enlaces físicos se utiliza una copia alternativa. No compartir enlaces ni exponer públicamente Web Preview: **la URL no tiene autenticación propia**. Las publicaciones antiguas pueden limpiarse manualmente por la política de retención.

**Limitaciones:** si termina el proceso del servidor o se apaga Cloud Shell, las descargas no estarán disponibles hasta volver a iniciar la aplicación. Esta página lee discos **locales**, no los de la otra cuenta. Si se dañó el disco o se borraron archivos, esta función no los puede reconstruir. Los resultados parciales se guardan después de cada PDF finalizado; una interrupción antes del primer resultado deja disponibles solo los PDFs originales para reintentar.

## Recuperación desde la pantalla principal

La sección **Recuperar o cambiar de lote anterior** permite seleccionar cualquier lote almacenado localmente y cargarlo como `ultimo_lote`. El programa integra respuestas del lote padre y los reintentos, y marca PDFs sin respuesta para reintentar. Los originales se buscan **solo dentro de la cadena de lotes relacionadas**, evitando confundir PDFs homónimos de diferentes tandas. Después de recuperar el lote, en el próximo render aparece el panel de reintentos.

Un ZIP recuperado puede combinar scripts AHK guardados en varios lotes padres; el centro de descargas los empaqueta en memoria y no deja otra copia permanente.

## Persistencia y ahorro de espacio

- El primer procesamiento conserva el PDF original en `uploads/<run_id>/` para permitir reintentos, abrirlo desde la tabla y reconstruir lotes interrumpidos.
- Al reintentar, cuando es posible se crea un **hard link** al mismo PDF original en vez de duplicar sus bytes. El worker no sobrescribe ese archivo compartido. Si no se puede crear el hard link, se conserva la alternativa de guardar el PDF normalmente.
- La vista de PDFs en `static/pdfs/` reutiliza archivos mediante hard links cuando es posible; abrir varias veces el mismo PDF no genera nuevas copias físicas.\n- CSV y ZIP de cada lote se escriben a un archivo temporal y luego se sustituyen atómicamente, de modo que otras pestañas no descarguen un archivo a medio escribir.
- El inventario cuenta los hard links una sola vez para estimar el espacio físico ocupado.
- El inventario y el escaneo de carpetas no se ejecutan en cada actualización de Streamlit: pulsa **Analizar almacenamiento ahora** cuando lo necesites.

## Limpieza local conservadora

La retención (7 días predeterminados) no implica borrado automático. En el panel **Almacenamiento local**:
1. Pulsa **Analizar almacenamiento ahora**.
2. Revisa tamaños y número de elementos candidatos.
3. Confirma que tienes respaldos y pulsa **Eliminar archivos antiguos**.

Se protegen el último lote y los lotes con `.procesamiento_activo`, junto con los uploads con el mismo ID. La marca se elimina cuando un lote acaba sin timeout externo. Una interrupción abrupta o un worker huérfano pueden dejar la marca: **no la borres sin verificar que ningún proceso del lote siga activo y sin rescatar los resultados**. La limpieza no toca Firestore ni los archivos del otro Cloud Shell.

Antes de borrar, es útil ejecutar:

```bash
df -h ~
du -sh ~/homcloud/uploads ~/homcloud/outputs ~/homcloud/static 2>/dev/null
```

## Seguridad

Las actas, resultados y AHK pueden contener información personal. **No expongas la vista previa de Cloud Shell a usuarios no autorizados.** Streamlit no es, por sí mismo, un sistema de autenticación para documentos. Los enlaces a PDF se publican nuevamente bajo `static/pdfs/` para permitir abrir el documento en otra pestaña; cualquier persona con su URL puede acceder mientras siga publicada. No constituyen enlaces autenticados. Se emplean identificadores difíciles de adivinar y un secreto local de 32 bytes, pero **la seguridad depende de no difundir las URLs y de restringir el acceso a Web Preview**. Limpia las publicaciones antiguas desde la interfaz cuando ya no sean necesarias. No guardes credenciales, claves API ni PDFs en Git o Firestore de preferencias.

## Despliegue y pruebas en ambas cuentas

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_configuracion_tabla test_pdf_enlaces test_configuracion_global test_operativa_compartida test_recuperacion_lotes test_integridad_app -v
bash ./run_cloudshell.sh
```

Realiza una prueba manual con 3 PDFs en una pestaña y abre **Recuperar resultados** en otra. Tras el primer PDF completado, confirma que se puede descargar su CSV y AHK sin esperar a los otros. Prueba a recuperar un lote interrumpido y reintentar exclusivamente los errores. Verifica que el enlace del nombre del archivo abre el PDF original en una nueva pestaña y que las publicaciones nuevas en `static/pdfs` son enlaces físicos al PDF de `uploads` (cuando el sistema lo permite). `static/exports` permanece sin nuevas copias.

## Sincronización compartida de prompts, modelo y timeouts

Cada tipo de configuración está en un documento **independiente** de Firestore:
- `homcloud_config/prompts_compartidos`: prompts Pregrado y Posgrado (hasta 30 000 caracteres por prompt).
- `homcloud_config/modelo_compartidos`: cadena del modelo OpenCode, vacía para utilizar el modelo por defecto.
- `homcloud_config/timeouts_compartidos`: timeout OpenCode (5–45 min) y PDF (5–90 min).

El documento de programas/planes y las preferencias de concurrencia/retención **no se modifican**.

### Primera publicación segura

**Elige primero el Cloud Shell que contiene los prompts y ajustes correctos, preferiblemente `infoclusiv`.** Haz respaldo de `prompts/`, `settings/modelo_opencode.txt` y `settings/timeouts.json` en una ubicación segura. Solo entonces, en la interfaz:

1. En **Configuración rápida**, abre **Sincronización de prompts, modelo y timeouts**.
2. Comprueba que todavía no haya documentos globales publicados. Hasta su publicación, los valores de cada cuenta siguen siendo locales.
3. Revisa Pregrado y Posgrado y pulsa **Publicar ambos prompts globalmente**.
4. Verifica el modelo activo y pulsa **Publicar este modelo globalmente**.
5. Revisa los timeouts y pulsa **Publicar estos timeouts globalmente**.
6. En el otro Cloud Shell, pulsa **Recargar ajustes desde Firestore** o abre una nueva sesión y verifica los tres ajustes.

**Nunca** se realiza una publicación automática desde un archivo de una cuenta. Si Firestore falla, la interfaz muestra un error y bloquea procesamientos y publicaciones mientras sea necesario; no actúa como si la última copia local fuera la versión global actual.

### Excepciones locales

En el mismo panel se puede activar de manera **independiente**:
- Usar prompts propios solo en este Cloud Shell.
- Usar modelo propio solo en este Cloud Shell.
- Usar timeouts propios solo en este Cloud Shell.

Las excepciones se guardan en `settings/excepciones_cloudshell.json`, excluido de Git. Con la excepción activada, el archivo local de esa cuenta tiene prioridad sobre Firestore. Con ella desactivada, se utiliza el valor global disponible, sin sobrescribir el archivo local.

Los cambios en el editor pueden aplicarse al lote de la sesión en curso. Para compartirlos debes pulsar el botón **Publicar ... globalmente** correspondiente. La publicación comprueba que la versión de Firestore no haya cambiado desde que abriste el editor. Si otra cuenta guardó una versión nueva, debes recargarla antes de volver a publicar.

### Historial y restauración

Cada actualización global de un documento existente archiva el contenido anterior en su subcolección `historial` de Firestore. Desde **Consultar historial de versiones** puedes elegir una versión anterior y restaurarla con confirmación; la restauración guarda a su vez un historial de la versión reemplazada.

La interfaz carga como máximo diez entradas por categoría por consulta. Para conservar un respaldo a largo plazo, exporta tus prompts fuera de Firestore según la política de datos de la institución. No introduzcas credenciales, secretos, ni información personal de estudiantes en los prompts compartidos.

### Verificaciones

```bash
cd ~/homcloud
git pull --ff-only origin main
.venv/bin/python -m unittest test_configuracion_global test_operativa_compartida test_recuperacion_lotes test_integridad_app -v
bash ./run_cloudshell.sh
```

Comprueba desde los dos Cloud Shell: publicación inicial, lectura global después de recargar, cambio en una cuenta detectado como revisión nueva en la otra, excepción local de modelo y timeouts, y restauración controlada de una versión anterior.

## Pendientes para una futura fase
- Añadir un semáforo distribuido para limitar consumo combinado de APIs de ambos Cloud Shell.
- Considerar respaldo externo privado y cifrado de históricos tras validar políticas de conservación de documentos.
- No automatizar borrados hasta contar con mecanismos de restauración probados y una forma supervisada de cerrar marcadores de procesos huérfanos.

## Validación automática de cambios

El workflow `.github/workflows/homcloud-ci.yml` compila los módulos y ejecuta las pruebas puramente locales en GitHub Actions en cada push a `main` y cada pull request. No utiliza credenciales, no descarga PDFs y no llama a Firestore ni APIs externas. Es adicional a las pruebas manuales en Cloud Shell; **un workflow creado no significa que ya haya aprobado**. Consulta la pestaña Actions para ver su resultado.
