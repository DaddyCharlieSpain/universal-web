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

## Auditoría de backups y recuperación

Ejecutar `./ops/contabo/backup-evidence.sh` en el VPS con acceso de lectura al
journal de cron. Emite horarios esperados, la última invocación observable y el
estado resumido del backup. Un inicio de cron no acredita su éxito. Correlacionar
hora y zona del VPS, inicio de las 03:00, identificador de la copia, verificación
de R2 y actualización de `last-success`. Revisar igualmente el inicio de las
06:00 y el resultado del watchdog. Si el journal no conserva registros, revisar
el syslog local. Mantener esos registros y cualquier nombre de objeto fuera de
Actions.

El procedimiento registrado en noviembre documenta SQLite mediante `.backup`,
`media.tar.gz`, configuración y cifrado mediante el remote `universal-cifrado`.
El 18 de noviembre se documentaron tres objetos coincidentes con
`rclone check --download`. La documentación también registra pruebas de correo
por `msmtp`. Verificar en el servidor cómo se propagan errores de empaquetado,
subida, verificación y SMTP, cuándo se escribe `last-success`, si el watchdog
detecta ausencia, fecha futura, ERROR y antigüedad superior a 26 horas, y si
evita alertas repetidas o emite recuperación. Probar fallo y recuperación con
estados temporales y un receptor de pruebas, con los scripts reales solo si
admiten configuración aislada. Si no, inspeccionar su código y preparar un
ensayo aislado antes de afirmar que el circuito está verificado. No dañar la
copia real, rotar credenciales ni habilitar borrado remoto durante el ensayo.

### Restauración aislada desde R2

Ejecutar como el usuario administrativo sin elevar a root, con la configuración
existente de rclone y desde la IPv4 autorizada del VPS. Elegir el ID concreto
en el prefijo registrado, usar un directorio privado recién creado y comprobar
que el conjunto contiene exactamente la base, la configuración y el archivo de
medios. Confirmar primero los nombres reales en el servidor. No usar
`sync`, ni volcar configuración o SQLite.

```bash
umask 077
drill=$(mktemp -d)
rclone --bind 155.133.198.70 copy "universal-cifrado:ID_DE_COPIA" "$drill/objects" &&
rclone --bind 155.133.198.70 check --download "universal-cifrado:ID_DE_COPIA" "$drill/objects"
```

Inspeccionar localmente la estructura de `media.tar.gz` y suministrar el
prefijo exacto (`.` si los medios están en la raíz). Confirmar cuota y espacio
libre para los medios descomprimidos. Ejecutar desde la copia verificada del
repositorio:

```bash
python3 ops/contabo/restore_051.py "$drill/objects" "$drill" \
  --media-prefix PREFIJO_DEL_ARCHIVO \
  --release /opt/universal-web/releases/0.5.1 \
  --theme /opt/universal-web/staging/carlosbarcelo-051/themes/carlosbarcelo
```

El ensayo rechaza enlaces, archivos especiales y rutas fuera del destino.
Extrae los medios en un árbol desechable, comprueba SQLite y referencias antes
y después de migrar la copia y compara recuentos de tablas. Verifica la
presencia del tema externo, que el backup de tres objetos no incluye. Conserva
ese tema con versión y huella independientes. La configuración recuperada se
comprueba como archivo descargado, sin cargarla ni ejecutar sus destinos
externos. Registrar ID, fecha, punto de recuperación, tiempo de ensayo y
resultado. Retirar de forma controlada los objetos descargados del directorio
privado al finalizar. Esta prueba es de datos, no de arranque HTTP.

## Preparación de la candidata 0.5.1

La 0.3.0 carece del actualizador firmado introducido en la 0.4.0. No ejecutar
`install.sh` ni reemplazar archivos en el árbol activo. Validar la release con
sus artefactos oficiales y dejarla bajo control de la cuenta administrativa.
La 0.5.0 añade temas con variantes y contenido por idioma. La 0.5.1 añade
ejemplos y ajustes de contraste a los temas iniciales. Esos cambios no prueban
que el tema personalizado funcione. La 0.5.1 arranca comprobando el esquema 15.
Probar con una copia de datos de 0.3.0 además de la de staging, que ya está en 15.

Preparar una instantánea sellada fuera de producción y staging con
`data/universal.sqlite`, `data/config.php`, `public/media` y
`themes/carlosbarcelo`. Obtener SQLite mediante la API online backup o
`.backup`, nunca mediante una copia del archivo vivo a solas en modo WAL.
Capturar DB y medios en un punto coherente, con los escritores pausados si
pueden cambiar durante la captura. Mantener la copia fuera del document root.
Revisar diferencias de contenido entre staging y producción. Construir la
versión de corte desde el conjunto de datos aprobado y obtener una captura
final bajo pausa de escrituras si la producción continúa recibiendo cambios.

```bash
umask 077
workspace=$(mktemp -d)
python3 ops/contabo/prepare-051.py /ruta/instantanea-sellada \
  /opt/universal-web/releases/0.5.1 "$workspace"
```

La preparación genera un directorio nuevo y migra únicamente su SQLite.
Inventariar también cambios locales en PHP, plantillas, configuraciones de
servidor, medios, trabajos y módulos de PHP. Revisar la configuración
resguardada y las rutas absolutas, permisos y metadatos necesarios. La
preparación conserva la configuración de la instantánea, por lo que antes de
arrancar una copia funcional se debe instalar en ella una configuración de
ensayo y neutralizar en esa copia SMTP, webhooks, publicación automática,
IndexNow, copias externas, actualización automática y cron. Ejecutar la copia
funcional sin salida de red. No reutilizar credenciales de producción como
credenciales de prueba.

### Pruebas funcionales en copia privada

| Área | Prueba y criterio de aceptación |
| --- | --- |
| Panel y autenticación | Acceder al panel con un administrador de ensayo, probar rechazo de credenciales erróneas, 2FA si aplica, cierre de sesión y restricción de un editor. Confirmar que una sesión cerrada pierde acceso. |
| Contenidos | Verificar portada, navegación, entradas, redirecciones y SEO. Crear un borrador sintético, editarlo, visualizarlo, publicarlo en la copia privada y comprobar el historial y la versión pública local. |
| Multimedia | Subir y recuperar un archivo de ensayo, comprobar el tipo de contenido y verificar que las referencias existentes responden. |
| Tema | Contrastar portada, menú, blog y vistas móvil y escritorio, comprobar assets, consola y animación. |
| Cloudflare Pages | Desde el panel generar el archivo de exportación en modo manual con contenido sintético. Validar rutas del tar, navegación, assets, canónicas, robots y referencias en una copia de la exportación. En una sesión aparte con credenciales dedicadas, subir exclusivamente los archivos públicos a un proyecto Pages de pruebas independiente y verificar la URL de preview. Comprobar que no aparecen config, SQLite, panel, tokens ni contenido privado. Documentar cómo se probará el formulario y dónde reside su backend antes de conectar la publicación real. |

Registrar versión, evidencia y resultado sin cuerpos de respuesta ni secretos.
Mantener el proyecto de Pages público y su DNS fuera del ensayo.

## Corte y reversión, pendientes de aprobación

1. Validar el restaurado real y la candidata, aprobar el origen y punto de datos
   del corte, acordar la ventana y conservar una copia externa verificada.
   Revisar cron, timers, PHP-FPM, Caddy, cualquier sincronización y rutas
   efectivas del CMS. Este mecanismo requiere que config, DB y medios efectivos
   queden dentro del árbol, que no haya montajes bajo ambos directorios y que el
   document root apunte a `/var/www/universal-web/public`. Si no se cumple,
   detener el procedimiento y adaptar el mecanismo al mapa real.
2. Tras la aprobación expresa, parar tráfico y todos los escritores (PHP-FPM,
   tareas de cron y timers, exportadores, actualizaciones y trabajos manuales).
   Cerrar conexiones SQLite y comprobar el cierre/checkpoint. Preparar la
   captura final si procede. Instalar la candidata como
   `/var/www/universal-web-cutover` en el mismo filesystem local, con raíz y
   código propiedad de root, configuración legible solo por quien la necesite y
   directorios de datos/medios asignados al usuario real de PHP-FPM. Revisar
   permisos a lo largo de ambos árboles. Mantener el slot fuera de cualquier vhost.
3. Como administrador, ejecutar `switch-051.sh deploy --approved`. Hace un
   intercambio atómico de directorios mediante `renameat2`, preserva el árbol
   antiguo completo en el slot y comprueba versión, integridad de la candidata y
   ausencia de sidecars. El argumento confirma que el operador recibió aprobación.
   El script no comprueba qué procesos están parados. El operador debe confirmar
   la pausa y la topología antes de llamarlo.
4. Reiniciar PHP-FPM para descartar código antiguo de OPcache y levantar el CMS
   con acceso de prueba controlado. Desde el VPS ejecutar
   `postcheck-051.sh CMS_HOST /RUTA_PUBLICADA /RUTA_MEDIA_O_TEMA`, una prueba
   TLS local sin seguir redirecciones, y repetir las comprobaciones de panel,
   lectura y medios. Revisar logs localmente y mantener deshabilitadas
   publicación y actualización automáticas hasta validar su destino. Reabrir
   tráfico y escritores solo tras superar las comprobaciones.
5. Si falla, detener de nuevo los escritores, cerrar SQLite y ejecutar
   `switch-051.sh rollback --approved`. Reiniciar FPM y repetir las pruebas
   sobre 0.3.0. El rollback recupera el estado anterior al intercambio. Si
   hubo escrituras desde el corte, preservar la copia 0.5.1 y reconciliarlas
   antes de reabrir el acceso de escritura. No alimentar la 0.3.0 con SQLite
   migrada. Revisar por separado cualquier publicación externa, que el
   intercambio local no revierte.

El gate SSH debe seguir limitado a las operaciones exactas ya autorizadas.
Mantener despliegue, restauración, rollback y rclone fuera de la llave de
Actions. Revisar permisos de toda la ruta del gate, claves, credenciales SMTP,
rclone y API de Pages. Conservar la comprobación estricta de la huella SSH.

## Ensayo funcional HTTP de la candidata

Se verificó la restauración 15 → 15 de la copia R2 del 21 de noviembre de
2026 y la migración real 14 → 15 de la copia del 19 de noviembre. Usar el
snapshot ya comprobado de esquema 15 para este ensayo. La base y el tar
de medios son las únicas entradas del backup. El script omite el config
original y genera su propia clave, usuario y contraseña efímeros. La
contraseña solo pasa a PHP por stdin y al servidor HTTP local, sin logs.
Se desactivan en la copia las credenciales importadas, los destinos de
publicación, SMTP, webhooks, offsite e IndexNow. El PHP de ensayo no
puede invocar sendmail ni ejecutar comandos del sistema. Aislar la red
también protege de conexiones que pueda intentar el código del tema.

Desde la sesión existente en Contabo, como operador sin privilegios, con
la rama del ensayo incorporada a la copia de scripts y el backup verificado:

```bash
drill="$HOME/uw-restore-051.m4wZaBLa"
umask 077
export UW_DRILL_HOST_NETNS=$(readlink /proc/self/ns/net)
unshare --user --map-current-user --net -- sh -ec '
  ip link set lo up
  exec python3 "$1/repo/ops/contabo/functional-051.py" "$1/objects/2026-11-21_03-00-01" "$1"
' sh "$drill"
```

Si el VPS prohíbe namespaces de usuario sin privilegios, el administrador
puede crear únicamente el namespace de red y bajar al usuario operativo
antes de ejecutar Python. Revisar primero el script y conservar la misma
restricción de una sola interfaz de loopback. No ejecutar el ensayo en la
red del host.

```bash
sudo unshare --net -- /bin/sh -ec '
  /usr/sbin/ip link set lo up
  export UW_DRILL_HOST_NETNS="$2"
  exec /usr/sbin/runuser -u carlosadmin -- /usr/bin/python3 "$1/repo/ops/contabo/functional-051.py" "$1/objects/2026-11-21_03-00-01" "$1"
' sh "$drill" "$(readlink /proc/self/ns/net)"
```

En Contabo se observó que el backup del día 21 declaraba esquema 15
aunque faltaban `path` y `content_at` en páginas y entradas. El ensayo
funcional toma una instantánea mediante la API de SQLite (incluye el WAL
si procede) y completa las columnas e índices exclusivamente en esa
candidata desechable. Sustituye los medios y el tema incluidos en la
release por el backup y el tema de staging, respectivamente.
El validador de staging rechaza un esquema 15 incompleto. Antes del corte
se requiere validar la estructura de la candidata definitiva por separado.

El ensayo exige un namespace distinto del host, únicamente loopback y
ausencia de ruta IPv4 externa. La candidata nace en un directorio
privado temporal. El cliente comprueba portada y ejecución del layout
copiado, rechazo de acceso anónimo y contraseña inválida, login y panel,
listados, creación, edición y lectura HTTP de una página de prueba,
subida y descarga de un medio sintético y cierre de sesión. Se
contrastan huellas del backup y del layout de staging. La edición, los
uploads y las sesiones solo se escriben bajo el directorio de ensayo.
El servidor se termina y la candidata se retira al salir. Si hay un
fallo, guardar solo la línea `functional_051=FAIL stage=...`. Tras una
interrupción abrupta, localizar y revisar únicamente los directorios
`http-drill-*` bajo el workspace privado y retirar los residuos de este
ensayo. El rollback de producción descrito arriba sigue siendo un
procedimiento separado.

### Resultado en GitHub Actions

El gate puede exponer solo `functional-051-status`. El trabajo de Actions
consulta un resultado reciente. No inicia PHP, no acepta rutas ni
argumentos remitidos por SSH y no tiene acceso a backups ni logs privados.

Tras revisar los cambios, instalar como root la consulta en
`/usr/local/libexec/universal-web/functional-051-status.sh` y crear
`/var/lib/universal-web-drill` con propietario root y modo 0755. Añadir al
gate una coincidencia exacta `functional-051-status` que ejecute la consulta
sin argumentos, conservando el rechazo por defecto. Registrar el éxito
solo después de observar la línea completa del ensayo:

```bash
sudo install -d -m 0755 -o root -g root /var/lib/universal-web-drill
sudo install -m 0755 -o root -g root   "$drill/repo/ops/contabo/functional-051-status.sh"   /usr/local/libexec/universal-web/functional-051-status.sh
printf '%s\n' 'functional_051=OK isolation=OK http=OK auth=OK admin=OK content=OK media=OK theme=OK' |
  sudo tee /var/lib/universal-web-drill/functional-051.status >/dev/null
sudo chown root:root /var/lib/universal-web-drill/functional-051.status
sudo chmod 0644 /var/lib/universal-web-drill/functional-051.status
```

Si se repite el ensayo, invalidar el resultado anterior antes de empezar.
Actions reporta la hora de registro y devuelve error si el resultado
falta, no es válido o tiene más de 24 horas. Este recibo es una
atestación administrativa del ensayo, no una ejecución remota. La
preview de Cloudflare Pages, la comprobación visual y el flujo de
alertas quedan como pruebas separadas.
