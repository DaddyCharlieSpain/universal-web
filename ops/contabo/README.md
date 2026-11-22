# Validación de Universal Web 0.5.1 en Contabo

| Operación | Comprobaciones |
| --- | --- |
| `validate-051` | Integridad y referencias de SQLite, esquema 15, sitio, tema personalizado y archivos multimedia referenciados por el sitio. |
| `test-051` | Validación anterior, copia consistente mediante la API de backup de SQLite y ejecución de `ensure_schema()` de la release sobre esa copia. Comprueba que se mantienen el esquema, la integridad y los recuentos. |
| `backup-status` | Estado registrado como OK y último éxito en las últimas 26 horas. Informa de la marca de modificación de los logs, que por sí sola no acredita una ejecución de cron. |

La versión 0.5.1 declara el esquema 15. Con staging en el esquema 15, el resultado esperado es que `ensure_schema()` no aplique cambios. La prueba usa el núcleo de la release y prescinde de la configuración del CMS, del arranque HTTP y de la publicación.

## Activación en el VPS

1. Desde la cuenta administrativa de Contabo, instalar el PHP de esta revisión como `/usr/local/libexec/universal-web/validate-051.php`, en un directorio administrado por root y con el archivo sin permiso de escritura para `deploy`. La release en `/opt/universal-web/releases/0.5.1` debe estar verificada y fuera del alcance de escritura de `deploy`.
2. En el dispatcher existente, añadir exclusivamente `validate-051`, `test-051` y `backup-status` a la lista de coincidencias exactas. Cada coincidencia debe ejecutar `/usr/bin/php /usr/local/libexec/universal-web/validate-051.php` con su operación literal como único argumento. Mantener el rechazo de cualquier otro comando y el comando forzado SSH existente. El proceso necesita PHP CLI con SQLite3 y PDO SQLite, lectura del staging, la release o los indicadores de backup según la operación, y escritura en su propio directorio temporal. Usar el mecanismo local restringido existente si el usuario de ejecución necesita esos permisos. Evitar reglas sudo con argumentos libres.
3. Tras integrar el workflow, lanzar `validate-051`, `test-051` y `backup-status` desde Actions. Para acreditar que las copias son automáticas, contrastar `last_success` con el registro de cron de las 03:00 y comprobar el watchdog de las 06:00 en el VPS. La fecha de una copia manual también puede aparecer en `last_success`.

Los logs de Actions solo necesitan el resultado, el esquema y las marcas de tiempo. No añadir volcados de SQLite, configuración, contenido de logs de backup ni credenciales.
