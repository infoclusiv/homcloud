# Preferencias globales y almacenamiento local (homcloud)

## Configuración compartida

Ambas instancias utilizan el mismo proyecto Firestore ya configurado para programas/planes. El documento adicional `homcloud_config/preferencias_operativas` almacena únicamente:
- `procesos_predeterminados` (1–20, valor inicial 4);
- `retencion_dias` (1–90, valor inicial 7).

En la sección **Configuración operativa** se elige un valor y se pulsa **Guardar predeterminado global**. La selección del control sin pulsar guardar solo afecta a la sesión. En el otro Cloud Shell se pulsa **Recargar predeterminado** o se inicia una nueva sesión para cargar lo guardado. Las escrituras usan la versión de Firestore para detectar ediciones simultáneas.

Si Firestore está configurado pero inaccesible, **no** se guardan preferencias localmente como si fueran compartidas. Cuando Firestore no está configurado, se usa `settings/operacion_global.json` local. El JSON se ignora en Git.

Nota: el valor configurado es **por instancia**, no un límite agregado. Si ambas instancias ejecutan 10 workers pueden existir hasta 20 procesos combinados. Monitoriza cuotas y latencia de proveedores.

## Descargas parciales y recuperación

Cada PDF terminado actualiza:
- `outputs/runs/<run_id>/resumen_resultados_parcial.csv`;
- `outputs/runs/<run_id>/scripts_ahk.zip` si hay AHK;
- una copia atómica de ambos en `static/exports/<run_id>/` para descargar durante la ejecución.

La interfaz publica los enlaces del CSV parcial y ZIP parcial al comenzar el lote: los archivos aparecen después del primer PDF completado. El enlace puede abrirse en otra pestaña sin esperar el último documento. Ante un reinicio de la sesión, aparece **Recuperar resultados parciales**: recupera la última tanda local disponible. No recupera archivos eliminados ni resultados de otra cuenta.

**Protección de datos:** los enlaces estáticos del servidor contienen datos posiblemente personales. Su URL tiene un identificador aleatorio y debe compartirse solo con personal autorizado. Si el Web Preview se expone públicamente, NO se deben utilizar descargas estáticas: utiliza un mecanismo autenticado o desactiva las descargas parciales. Los enlaces estáticos aleatorios no constituyen control de acceso. El método de publicación existente de PDFs originales en `static/pdfs` tiene esta misma limitación de seguridad. La limpieza de archivos antiguos también elimina las copias estáticas tras confirmación.

## Almacenamiento

La sección **Almacenamiento local** muestra tamaños de `uploads/`, `outputs/runs/`, `static/pdfs/` y `static/exports/`. Ofrece limpieza **manual y confirmada** de elementos con última modificación anterior a los días de retención configurados, conservando el lote más reciente y los IDs de la sesión actual. Nunca modifica Firestore ni el otro Cloud Shell.

La limpieza de copias antiguas puede invalidar enlaces a PDFs y resultados de lotes anteriores; descarga o respalda antes de limpiar. La aplicación no puede garantizar recuperación después de un borrado.

Recomendado antes de empezar un lote: verificar el espacio disponible desde la terminal con `df -h ~` y comprobar los archivos con `du -sh ~/homcloud/uploads ~/homcloud/outputs ~/homcloud/static 2>/dev/null`.

## Configuraciones candidatas para próxima fase

- Prompts Pregrado/Posgrado: **globales** con historial y revisión, tras respaldo y aprobación; hoy siguen locales.
- Modelo OpenCode: **global por defecto con sobrescritura local**, porque cada cuenta puede tener modelos diferentes.
- Timeouts: **globales con sobrescritura local** y límites validados; hoy siguen locales.
- Frecuencia de limpieza automática: mantener **desactivada** hasta contar con restauración y protección de trabajos realmente activos.
- Claves de API, tokens, credenciales ADC, uploads originales, resultados con datos personales: **NO** incluir en Firestore de preferencias ni en Git.
- Cuota agregada de dos Cloud Shell y bloqueo distribuido: proponer mecanismo específico; la preferencia de workers no es un semáforo entre instancias.
