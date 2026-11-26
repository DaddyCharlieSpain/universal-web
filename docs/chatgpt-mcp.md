# Universal Web y ChatGPT

## Punto de partida

Universal Web 0.5.1 expone JSON-RPC por HTTP sin estado en `/mcp` y
negocia 2025-11-25, 2025-06-18, 2025-03-26 y 2024-11-05.
Autentica tokens nativos con Bearer o X-MCP-Token. Guarda una huella,
permite revocación y vuelve a resolver el rol del propietario. Tiene
permisos read, write, publish, messages, code y backup. Tokens globales
pueden seleccionar el sitio. El endpoint nativo no ofrece OAuth.

El perfil ChatGPT usa POST JSON por HTTPS en `/mcp/chatgpt`, acepta
notificaciones con 202 y devuelve 405 para GET sin stream. El descubrimiento
RFC 9728 queda en `/.well-known/oauth-protected-resource/mcp/chatgpt`.
El endpoint está desactivado sin configuración y conserva la comprobación
de red del MCP existente. El endpoint nativo sigue disponible para otros
clientes. La conexión ChatGPT usa un servidor de autorización externo.
Universal Web actúa como servidor de recursos y valida mediante introspección
HTTPS cada token. No implementa un servidor de autorización propio.

## Configuración de staging

1. Desplegar los archivos de esta rama exclusivamente en un staging
   autorizado con HTTPS y datos de ensayo. Elegir un proveedor OAuth que
   anuncie PKCE S256, acepte un cliente ChatGPT registrado y devuelva
   issuer, subject, client_id, audience, exp y scope en introspección.
   El recurso debe coincidir exactamente con la URL completa del MCP.
   Usar el redirect URI exacto que muestre ChatGPT. Consultar
   https://developers.openai.com/plugins/build/auth para la metadata del
   proveedor y las modalidades de registro de cliente.
2. Crear en ese sitio un editor dedicado y un token nativo de alcance
   exclusivamente read, limitado al sitio. El adaptador solo necesita el ID
   numérico del token. No introducir el valor Bearer nativo en ChatGPT.
   La revocación del token o la pérdida del rol editor retira la vinculación.
3. Configurar en el archivo privado del CMS la clave `chatgpt_mcp` con
   `enabled` (booleano), `host` (hostname de staging), `issuer`,
   `introspection_url`, `introspection_id`, `introspection_secret`
   (cliente confidencial del recurso), `client_id` (cliente OAuth de ChatGPT),
   `subject` (identidad OAuth del operador), `site_slug` y `token_id` (entero).
   El fichero debe quedar fuera del document root y legible solo por los
   usuarios necesarios. No incluir secretos en el repo, líneas de comandos ni
   logs. El adaptador requiere PHP cURL. Permitir salida HTTPS solo al
   endpoint de introspección según la política del staging.
4. Verificar en staging que el endpoint y el documento de descubrimiento
   sean alcanzables por ChatGPT. Un proxy que exige una sesión interactiva
   de Cloudflare Access antes de devolver el 401 MCP impide el flujo.
   Verificar que el plano de entrada elegido mantenga los controles del
   panel y de otros endpoints. Si el staging actual no es compatible,
   acordar un ingreso dedicado para MCP o un túnel seguro cuando el cliente
   lo soporte. No modificar la configuración de producción en esta fase.

## Validación

- Ejecutar `php -l app/mcp-chatgpt.php`, `php -l app/bootstrap.php` y
  `php tests/mcp-chatgpt-readonly.php`.
- Sin credencial, el POST de inicialización devuelve 401 y anuncia metadata.
  Un token revocado, caducado o de otro cliente, identidad o recurso se rechaza.
- Conectar el plugin personalizado en ChatGPT, completar OAuth y verificar
  initialize, tools/list y lectura de una entrada existente. Intentar
  post_save, media_upload, publish_now y post_delete directamente en el
  entorno de ensayo y verificar su rechazo sin que cambie SQLite.
- Confirmar que los borradores y contenido multimedia que se leen pueden
  compartirse con ChatGPT. El perfil excluye mensajes, secretos, backups,
  cambios de código y enlaces de previsualización firmados del site_get.
  Los resultados pueden contener texto editorial no confiable.
- La integración del publicador se comprobará en un destino de ensayo
  aislado. Las lecturas nunca deben marcar el sitio como pendiente.
  No usar el publicador productivo para probar permisos OAuth.

## Escritura y recuperación

Abrir una segunda fase solo después de validar la lectura real. Diseñar
herramientas separadas, con alcance adicional de borradores, que comprueben
el estado actual y fuercen estado draft sin publicar ni editar entradas
publicadas. Media debe anticipar que algunos archivos pueden acabar en la
exportación pública. SEO conserva lectura y edición solo en borradores.
Mantener publicación y eliminación en el panel hasta una autorización
explícita para operaciones concretas. Antes de habilitar escrituras, verificar
si una edición en borrador marca la cola y si el artefacto estático cambia.

Para recuperar, desactivar `enabled`, revocar el token nativo y la concesión
OAuth y rotar la credencial de introspección si se sospecha exposición.
Revertir el commit de la rama solo si hace falta retirar los archivos.
No se introducen tablas ni se modifica el publicador Wrangler en esta fase.


## Perfil Keycloak para staging

- Inventariar CPU, memoria disponible, disco, servicios, puertos, runtime
  de contenedores, PHP y la instalación de staging antes de provisionar.
  Inspeccionar los realms y los clientes por nombre y configuración desde
  una sesión administrativa. No exportar secretos ni reutilizar clientes
  de producción. Reutilizar un cliente solo si está dedicado a este staging,
  tiene el callback exacto y supera los controles de abajo.
- Usar un realm y una base de datos aislados y una instalación CMS con
  contenidos sintéticos. Mantener los servicios administrativos en
  loopback o red privada. La prueba desde ChatGPT exige una ruta HTTPS
  aprobada para el MCP y para el inicio de sesión de Keycloak. Evaluar
  el HTTPS ya disponible o un túnel autorizado; no modificar DNS ni
  los controles de acceso de producción.
- En la versión de Keycloak seleccionada, verificar el soporte de
  `resource-indicators` (experimental en la documentación revisada).
  Exigir `resource` idéntico en autorización y canje. Registrar el servidor
  de recursos con `resource_url` igual a la URL canónica completa del MCP
  y configurar el mapper Audience para el cliente de ChatGPT.
- Preferir cliente preinscrito con Authorization Code y PKCE S256,
  sin password grant ni callbacks comodín. Usar la URI literal de la ficha
  de conexión, que puede ser específica del callback del plugin. Vincular
  únicamente el alcance `uw:read` y el usuario sintético. No habilitar
  registro dinámico público para esta prueba.
- Desde Keycloak 26.6.2 el cliente de introspección debe pertenecer
  a la audiencia del token. Probar que el cliente confidencial de recursos
  puede introspectar manteniendo este control. Si el modo RFC 8707 emite
  solo la URL en aud, comprobar si se puede usar esa URL como ID del
  cliente confidencial, además de como resource_url. Una respuesta
  inactive bloquea la conexión; no habilitar excepciones de compatibilidad.
- Pruebas de aceptación: discovery anuncia S256; se rechazan callback
  ajeno y resource incorrecto o cambiado en el canje; introspección
  autenticada devuelve active, iss, sub, client_id, aud, exp y uw:read;
  el adaptador rechaza otro emisor, sujeto, cliente, audiencia o alcance;
  ChatGPT enumera herramientas y lee un artículo sintético. Probar la
  denegación de escritura en staging y que la lectura no encola publicación.
- Recuperación del staging: desactivar el perfil, revocar sesiones y
  credenciales de prueba, cerrar el ingreso dedicado y detener solamente
  la instancia de Keycloak de staging. Conservar la copia de configuración
  anterior. No tocar servicios productivos.

Referencias: https://www.keycloak.org/securing-apps/mcp-authz-server,
https://www.keycloak.org/docs/latest/upgrading/ y
https://developers.openai.com/plugins/build/auth.


## Entrada HTTPS con Cloudflare Tunnel

Propuesta pendiente de autorización DNS: `mcp-staging.carlosbarcelo.es`
y `auth-staging.carlosbarcelo.es`, ambos en un túnel dedicado
`uw-mcp-staging`. Inventariar `cloudflared` en el VPS y túneles en la
cuenta antes de provisionar. Reutilizar el ejecutable si está instalado y
soportado. Reutilizar un túnel solamente si es de staging y no sirve rutas
productivas. Un túnel dedicado puede ejecutarse con un usuario propio,
proxy dedicado en loopback y una credencial de conector en un fichero
privado; no usar una credencial administrativa general de la cuenta.

El proxy debe devolver 404 fuera de las rutas expresamente permitidas:

- Host MCP: solo `/mcp/chatgpt` y
  `/.well-known/oauth-protected-resource/mcp/chatgpt`.
- Host OAuth: discovery OIDC/RFC 8414 para `uw-mcp-staging`, las rutas
  necesarias del flujo OIDC y `login-actions` de ese realm, y los recursos
  estáticos requeridos por la pantalla de login. Mantener `/admin`,
  `/realms/master`, gestión y métricas fuera de la entrada. La
  introspección requiere HTTPS y autenticación de cliente confidencial;
  preferir una ruta privada si se dispone de TLS interno verificable.
- No publicar el servidor Keycloak de diagnóstico en modo dev. Preparar
  una instancia aislada con hostname HTTPS explícito y proxy confiable.
  Mantener la validación de audiencia activa. No poner una pantalla de
  Cloudflare Access delante del descubrimiento ni del intercambio OAuth.
- Verificar 404 en las rutas administrativas, 401 con metadata en el MCP
  anónimo y el recorrido OAuth real antes de ampliar el acceso. La reversión
  consiste en retirar las rutas nuevas, parar el conector dedicado y revocar
  su credencial sin tocar DNS ni servicios existentes.

Referencias: https://developers.cloudflare.com/tunnel/concepts/routing/
y https://www.keycloak.org/server/reverseproxy.

## Validación en ChatGPT y Contabo

El 25 de noviembre de 2026 se verificó el complemento en el laboratorio
sintético `universal-web-mcp-lab`. La conexión OAuth llegó a Keycloak y
`post_list` devolvió cuatro entradas (tres publicadas y un borrador).
También se probaron desde ChatGPT `post_get`, `page_list`, `page_get`,
`media_list` y `seo_analyze`. `seo_audit` devolvió inicialmente JSON-RPC
`-32603`. En dos llamadas posteriores devolvió 100/100, sin incidencias
para el contenido sintético. La causa del error inicial sigue sin
confirmarse. Las siete herramientas de lectura se han ejecutado con
éxito desde ChatGPT.

- El cliente de ChatGPT usa PKCE S256 y la URI de retorno exacta que
  muestra ChatGPT. El alcance editorial es `uw:read`. Keycloak debe
  aceptar también los ámbitos OIDC de la solicitud. En el intento
  observado fueron `openid email offline_access uw:read`. El cliente
  tiene `email`, `profile`, `offline_access` y `uw:read` como
  ámbitos opcionales. `offline_access` permite renovar la sesión.
- El proxy publica `userinfo` únicamente para el realm de staging.
  Sin token, debe devolver 401. Las rutas de administración del CMS y
  de Keycloak siguen fuera de las rutas permitidas.
- Si el canje devuelve 200, la introspección 401 y el MCP 503, revisar
  la autenticación del cliente de introspección. El identificador es
  la URL del recurso y contiene dos puntos. El commit `4da07ce`
  codifica el identificador y el secreto antes de construir HTTP Basic.
- Tras corregir la introspección, usar **Actualizar herramientas** en
  los detalles del complemento. La presencia de una cuenta vinculada
  solo acredita la vinculación. Para probar la lectura, seleccionar
  el complemento en un chat nuevo y ejecutar `post_list`.
- Limitar el diagnóstico HTTP al proxy de staging y registrar solo
  host, método, ruta sin parámetros y estado. Restaurar la directiva
  de registro anterior al terminar. Conservar la validación del
  emisor, audiencia, sujeto, cliente, expiración y alcance.

### Comprobaciones públicas de aislamiento

Desde fuera de Contabo, `initialize`, `tools/list` y `tools/call`
(`post_list`) devolvieron HTTP 401 sin token. También se observó
HTTP 401 en UserInfo y HTTP 404 en las rutas de administración de
staging y el descubrimiento del realm `master`. El catálogo recibido
desde ChatGPT contiene las siete herramientas esperadas de lectura.

El 25 de noviembre de 2026 el administrador confirmó la rotación del
token de `uw-mcp-staging` y su actualización en Contabo. El panel de
Cloudflare mostró una réplica activa y dos rutas. Tras el reinicio,
los metadatos de MCP y OAuth respondieron por HTTPS con 200 y
`post_list` volvió a funcionar desde ChatGPT con cuatro entradas de
prueba. El despliegue MCP en producción requiere autorización específica.

## Fase 2: borradores exclusivamente en el laboratorio

La rama `ops/chatgpt-mcp-drafts` mantiene el perfil de lectura por defecto.
Para habilitar escritura, usar la base sintética de
`universal-web-mcp-lab`, el host `mcp-staging.carlosbarcelo.es` y el
realm `uw-mcp-staging`. Activar `chatgpt_mcp.drafts_enabled = true`
solo en el archivo privado de configuración de ese laboratorio.
Mantener intactas las credenciales, rutas y unidades de producción.

Crear en ese realm el ámbito de cliente OIDC `uw:drafts:write` con
`include.in.token.scope=true`. Asignarlo como opcional a
`chatgpt-uw-staging` y solicitarlo explícitamente en la aplicación de
staging, junto a `uw:read`. Una sesión con solo `uw:read` conserva
el catálogo de lectura. Renovar el consentimiento y actualizar las
herramientas para usar la escritura. Confirmar que siguen vigentes
PKCE, audiencia, emisor, cliente y sujeto de staging.

- `draft_create` crea por título con estado borrador. Un slug
  duplicado se rechaza. `draft_update` modifica por ID, mantiene el
  slug e idioma existentes y conserva los campos omitidos.
- `post_get` devuelve los metadatos SEO. Los campos editables con
  `draft_update` son `seo.title`, `seo.description` y `seo.noindex`.
- El guardado verifica el estado y los indicios de publicación
  anterior dentro de una transacción SQLite `BEGIN IMMEDIATE`.
  Rechaza entradas publicadas, fechas de publicación existentes e
  historial conservado con estado publicado. Las herramientas
  genéricas de borrado, publicación, reprogramación y subida quedan
  fuera de la lista permitida.
- `mcp.draft.create` y `mcp.draft.update` quedan en `audit_log` con
  el actor de la vinculación MCP y el slug. Las ediciones conservan
  historial de contenido. Estas acciones no marcan `site_publish`
  como pendiente y un guardado de borrador no encola IndexNow.
- La biblioteca sintética se puede inspeccionar con `media_list`.
  La fase no admite subidas, descargas remotas ni edición de portada,
  audio o imagen SEO mediante los campos dedicados. Para una fase
  posterior, valorar referencias por ID de la biblioteca del mismo
  sitio y cargas locales en un directorio exclusivo de staging, con
  MIME real, límites y rechazo de URL remota en el servidor.

### Prueba de aceptación y recuperación

Ejecutar los contratos y la prueba de persistencia en un directorio
de datos vacío, con PHP CLI y SQLite:

```bash
php tests/mcp-chatgpt-readonly.php
test_data=$(mktemp -d)
(UW_DATA="$test_data" php tests/mcp-chatgpt-drafts.php)
rm -rf -- "$test_data"
```

La prueba de persistencia usa una instalación sintética, un registro
centinela de publicación estática sin credenciales y una entrada
publicada inmóvil. Comprueba creación, edición SEO parcial, auditoría,
rechazo con solo lectura, edición de publicados, publicación y borrado.
Tras habilitar el ámbito en Keycloak, repetir desde ChatGPT con un
borrador sintético. Comprobar la entrada y su estado mediante
`post_get`. Revisar la fila de publicación y los eventos de auditoría
del laboratorio. La prueba por OAuth y HTTP es independiente del
contrato PHP.

Para cortar la escritura, desactivar `drafts_enabled` en el
laboratorio. Quitar el ámbito opcional del cliente y revocar su
concesión o sesión offline para impedir nuevas renovaciones. La lectura
puede volver a vincularse con `uw:read`. Para recuperar el contenido,
revisar el historial desde el panel local de laboratorio o restaurar
una copia de su SQLite. Para revertir código, recuperar los archivos
de la revisión de solo lectura y conservar la base sintética y la
auditoría. No aplicar esa restauración a producción.

### Resultado de aceptación en Contabo

El 25 de noviembre de 2026, ChatGPT creó el borrador sintético
`prueba-mcp-fase-2-staging` (ID 6) con `draft_create` y cambió
únicamente título SEO, descripción y `noindex` con `draft_update`.
Una lectura independiente mediante el complemento original confirmó
la persistencia del borrador y sus metadatos. La prueba aislada en
Contabo también pasó y verificó que la fila de publicación estática
y el registro de contenido publicado permanecieron intactos.

Una segunda edición autenticada actualizó solo el cuerpo Markdown del
borrador ID 6. La lectura posterior por el complemento original confirmó
el texto nuevo, el SEO idéntico, el estado `draft` y la fecha de
publicación nula.

## Fase 3: multimedia y preparación para producción

La rama de integración añade dos herramientas de staging. La consulta
de la biblioteca sigue usando `media_list` con `uw:read`.

| Operación | Ámbitos requeridos |
| --- | --- |
| `draft_image_upload` | `uw:read` + `uw:drafts:media` |
| `draft_cover_set` | `uw:read` + `uw:drafts:media` + `uw:drafts:write` |

La subida recibe PNG o JPEG en base64 puro, hasta 32 KiB antes de
normalizar, 1024 píxeles por lado y 512 KiB después de decodificar y
reescribir con GD. El nombre debe ser simple y el texto alternativo
es obligatorio. No hay descargas remotas, SVG ni sustitución de
archivos existentes. La portada se selecciona por ID de una imagen
local del mismo sitio, con formato, tamaño y ruta comprobados. La
asignación usa la misma transacción y política de borrador que las
ediciones de texto. La subida registra `mcp.draft.media.upload` y
la asignación, `mcp.draft.update`.

### Revisión técnica

- Universal Web conserva la versión 0.5.1 y el esquema 15. No se añaden
  tablas, migraciones ni dependencias de Composer o npm al CMS.
  La subida requiere PHP GD con PNG y JPEG. SQLite y cURL siguen
  interviniendo en persistencia e introspección respectivamente.
- Se revisó la separación entre metadatos, catálogo, ejecución,
  validación de claims y token local. Las pruebas de contrato cubren
  expiración, `nbf`, token inactivo, emisor, audiencia, sujeto,
  cliente y alcance. El servidor consulta Keycloak en cada solicitud.
  Falta observar expiración y revocación con una sesión OAuth de
  prueba en Contabo, sin registrar ni copiar el token.
- Las escrituras quedan bajo el host, realm y sitio sintético
  permitidos. El sitio productivo y sus credenciales quedan fuera
  de la activación. El historial actual es acotado: si una
  despublicación manual borra la fecha y el historial ya se purgó,
  no hay prueba permanente de publicación anterior. Resolver este
  límite antes de habilitar edición de borradores en producción.
- El exportador copia el árbol multimedia completo de cada sitio.
  Aislar físicamente raíz pública y base de staging. No vincular su
  destino estático al proyecto Pages productivo. Las acciones
  `mcp.draft.*` no marcan la fila de publicación. Se comprobó con
  una fila centinela de publicación automática en SQLite sintético.
  No se ejecutó Wrangler ni se alteró el publicador.
- La prueba aislada pasó creación, edición y portada, rechazo por
  ámbito, formato o tamaño, rechazo de portadas en publicados,
  auditoría, `integrity_check` y `foreign_key_check`. Se ejecutó
  con PHP WASM con GD en una copia desechable y después con PHP
  nativo en Contabo. La aceptación desde ChatGPT figura abajo.

### Despliegue y rollback

1. Crear una copia consistente de la SQLite de laboratorio mediante
   la API de backup de SQLite. Guardar de forma privada la revisión,
   configuración y multimedia de staging. Verificar la copia con
   `PRAGMA integrity_check` y `PRAGMA foreign_key_check`.
2. Instalar la revisión fijada en una copia de trabajo independiente.
   Comprobar que `UW_DATA`, la raíz pública y `public/media` resuelven
   dentro del laboratorio y que GD admite PNG/JPEG. Ejecutar los dos
   scripts de aceptación con datos temporales vacíos.
3. Mantener el servicio productivo, las rutas DNS y el publicador.
   Activar `chatgpt_mcp.draft_media_enabled = true` en el laboratorio.
   Añadir `uw:drafts:media` como ámbito OIDC opcional del cliente de
   staging y solicitarlo explícitamente en una sesión de prueba.
   Actualizar herramientas. Probar con una imagen sintética y un
   borrador de ensayo. Verificar auditoría y fila del publicador.
4. Probar por separado la expiración y revocación en una sesión
   desechable. Tras expirar o invalidar el token, una solicitud
   que lo reutilice debe devolver 401. Probar también un token válido
   con solo lectura. Debe quedar excluido del catálogo de escritura
   y su llamada directa debe rechazarse. La renovación de ChatGPT
   puede ocultar la expiración; comprobar el token concreto desde
   un cliente de diagnóstico, sin imprimirlo.
5. Para cortar multimedia, poner `draft_media_enabled = false` y
   retirar el ámbito opcional. Revocar las concesiones y sesiones
   correspondientes si procede. Si hay que volver atrás en código,
   apuntar el servicio de staging a la revisión de fase 2 y
   recargar solo ese servicio. Recuperar portada desde el historial.
   Conservar la auditoría y evitar restaurar toda la base si basta
   revertir la configuración.

Para producción se requiere aprobación específica y una propuesta
separada de identidad OAuth, aislamiento, tratamiento de activos
exportados y marcador duradero de publicación previa. La rama no
habilita la escritura en producción.

### Aceptación multimedia en Contabo

El instalador verificó la separación de rutas de SQLite, configuración
y multimedia, pasó los contratos y la prueba SQLite con PHP nativo y
validó la copia de retorno. El MCP anunció los tres ámbitos por HTTPS.
Desde ChatGPT, el PNG sintético `mcp-fase3-prueba.png` quedó en la
biblioteca con ID 7 y se asignó como portada del borrador ID 6.
La consulta independiente confirmó la misma ruta en el medio y el
borrador, estado `draft`, fecha de publicación nula y `noindex=true`.
Una consulta posterior en modo de solo lectura verificó la integridad
SQLite y sus claves foráneas. El evento 27 registró la subida del medio
ID 7 y el evento 28 registró la edición posterior del borrador ID 6.
Las filas publicadas y las filas de `site_publish` del laboratorio
coincidieron con la copia previa a la activación multimedia.
El ensayo posterior de caducidad y revocación figura en el cierre OAuth.

### Ensayo OAuth con credenciales desechables

`ops/contabo/mcp-oauth-drill.py` usa PHP nativo y el Keycloak de Contabo.
Requiere iniciar sesión con privilegios para crear, configurar, consultar
y eliminar un cliente y su cuenta de servicio en `uw-mcp-staging`, y
leer el ámbito `uw:read` de ese realm. No requiere sudo. No modifica el
cliente de ChatGPT, su usuario ni sus sesiones.

El ensayo arranca una copia del CMS solo en loopback, con una copia
SQLite consistente y escritura MCP desactivada. Solicita dos tokens
reales de 30 segundos. Para ambos verifica que la introspección los
devuelve activos y que `post_list` permite leer. Deja expirar el
primero y revoca el segundo por el endpoint OAuth del realm. Verifica
introspección HTTP 200 con `active=false` y MCP HTTP 401 en ambos casos,
incluida la comprobación de que el token revocado aún no había vencido.
Compara todas las filas SQLite y comprueba la integridad y las claves
foráneas. El cliente se elimina al salir y se comprueba su ausencia.
Si se interrumpe por SIGKILL, eliminar exclusivamente el cliente
`uw-mcp-drill-…` cuyo identificador figure en la salida. Los informes
solo contienen horas, eventos, códigos y resultados.

El limitador de solicitudes MCP conserva una ventana de 120 peticiones
por minuto en archivos privados y con bloqueo, separados de SQLite.
Así un rechazo no modifica la base para actualizar los contadores.
El espacio queda limitado a 4096 grupos. Si dos IP coinciden en un
grupo, comparten su cuota. La prueba local cubre saturación y reinicio
de la ventana. El ensayo completo pasó en Contabo con la revisión `7dcce62`, en una
copia de trabajo aislada. El servicio activo conserva su revisión anterior.

### Cierre OAuth en Contabo

El 25 de noviembre de 2026, entre 21:37:28 y 21:38:12 UTC,
la revisión `7dcce62` superó el ensayo con un cliente y cuenta de
servicio desechables del realm `uw-mcp-staging`.

| Comprobación | Evidencia |
| --- | --- |
| Emisión y audiencia | Ambos tokens: HTTP 200 y audiencia esperada |
| Lectura válida | Ambos tokens: introspección 200, activo; MCP 200, autorizado |
| Caducidad real | Introspección 200, inactivo; MCP 401 |
| Revocación real antes de vencer | Revocación 200; introspección 200, inactivo; MCP 401 |
| SQLite | Integridad y claves foráneas correctas; todas las filas intactas |
| Limpieza | Cliente de prueba eliminado y ausencia comprobada |

La traza registró horas, códigos HTTP y decisiones, sin incluir tokens
ni secretos. El ensayo no cambió el cliente, usuarios ni sesiones de
ChatGPT. Los intentos anteriores se detuvieron antes de probar caducidad
por un 403 en la introspección pública. La solicitud del ensayo se
alineó con la del CMS y la ejecución final superó todas las comprobaciones
manteniendo la validación de audiencia.

### Plan de cambio productivo para revisión

1. Aprobar explícitamente el alcance, la revisión y la ventana.
   Empezar con `uw:read` y un cliente, usuario y enlace CMS propios
   de producción. Definir qué borradores y medios pueden consultarse.
   Mantener la configuración y los secretos fuera del repositorio.
2. Verificar una copia consistente de SQLite, configuración y medios.
   Identificar el árbol activo y conservar una revisión de vuelta.
   Confirmar la configuración y el último despliegue recuperable de
   Pages antes de cualquier cambio del CMS.
3. Preparar un candidato con el endpoint desactivado y ejecutar las
   pruebas del lector, proxy y OAuth contra un entorno separado.
   Revisar rutas y límites sin habilitar escritura ni tareas de
   publicación. La política duradera de publicación previa y la
   exportación selectiva de medios son requisitos para plantear
   escritura productiva.
4. Tras aprobación, instalar la revisión con un procedimiento de
   cambio reversible. Habilitar solo lectura y comprobar 401 anónimo,
   catálogo, una lectura autorizada y ausencia de cambios en las
   filas del publicador. Preservar el flujo estático existente.
5. Ante cualquier fallo, desactivar el endpoint, retirar la concesión
   y volver al árbol y configuración anteriores. Conservar SQLite
   y auditoría salvo que exista una incidencia de datos que requiera
   restaurar la copia consistente. Conservar producción y Pages
   intactos durante el ensayo de staging.

### Comprobación previa a la primera prueba productiva

La candidata `62aec2b` superó en una copia de trabajo limpia los
contratos MCP y la prueba de persistencia con PHP WASM, las
comprobaciones de sintaxis del instalador y del ensayo OAuth y
`git diff --check` del último cambio. El laboratorio activo siguió
devolviendo el borrador sintético ID 6 con su portada y estado
`draft`. El cierre OAuth de la candidata se ensayó por separado
en Contabo.

Línea base pública del 25 de noviembre de 2026: la portada de
`carlosbarcelo.es` devolvió 200 y `www` redirigió con 301 al dominio
principal. En el host CMS, tanto `/admin/` como la URL prevista de
metadatos MCP redirigieron con 302 a Cloudflare Access. Aún no se
ha verificado un trayecto público productivo compatible con OAuth
de ChatGPT. La propuesta debe identificar el trayecto exacto de
MCP y metadatos y mantener protegidos panel y rutas privadas.

Antes de abrir una prueba de solo lectura, confirmar con el
administrador la revisión instalada, una copia reciente y su
restauración aislada, el despliegue Pages de retorno, la identidad
OAuth productiva y los datos que se autorizan. El catálogo actual
de lectura incluye borradores: si se desea probar solo con contenido
publicado, debe aplicarse y verificarse ese límite antes de enlazar
ChatGPT. No se verificaron esas condiciones sobre datos de producción
durante esta revisión.

### Primera prueba productiva autorizada para preparación

El perfil fuera del laboratorio se limita por defecto a un catálogo
de páginas y artículos publicados. Las cuatro herramientas son
`page_list`, `page_get`, `post_list` y `post_get`. Devuelven solamente
slug, título, idioma, ruta pública y, en artículos, fecha de
publicación. El texto y los medios ya publicados se consultan en
la web pública. El perfil no entrega bloques, Markdown, traducciones
de borradores, inventario multimedia, mensajes ni configuración.
Un token con ámbitos adicionales tampoco amplía el catálogo.
En staging se puede ensayar con `chatgpt_mcp.published_catalog=true`
en una copia de trabajo privada y una sesión de prueba.

Las pruebas SQLite con datos sintéticos comprueban listado y consulta
por slug, rechazo de borradores y artículos futuros, filtrado de campos,
rechazo de herramientas fuera del catálogo y que la fila de
`site_publish` no cambia. El ensayo real de caducidad y revocación
está registrado arriba. Repetir los contratos con PHP nativo de
Contabo sobre la candidata antes de enlazar la identidad productiva.

#### Evidencia administrativa previa

- Identificar el árbol activo de Contabo en `/var/www/universal-web`.
  Registrar versión, esquema declarado y revisión Git si existe;
  para una release sin Git, registrar las huellas SHA-256 de
  `app/core.php` y `app/bootstrap.php` y contrastarlas con el
  manifiesto de la release. Registrar el estado de PHP-FPM,
  Nginx y del publicador configurado, sin volcar variables.
- Confirmar que la copia reciente procede de la instalación activa.
  Verificar hashes de la copia y recuperar SQLite y medios en un
  directorio privado independiente. Seguir el procedimiento de
  `ops/contabo/README.md`. Verificar `integrity_check`,
  `foreign_key_check`, esquema, tema y presencia de configuración.
  Si el backup externo omite configuración o tema, localizar y
  comprobar sus copias privadas por separado. Conservar el árbol
  anterior activo hasta disponer de una ruta de vuelta verificada.
- En Pages, abrir `carlos-barcelo-personal` → Implementaciones.
  Registrar ID y URL del despliegue productivo actual y de un
  despliegue productivo exitoso anterior disponible para rollback.
  La revisión del menú no ejecuta el rollback. La URL pública por
  sí sola no acredita que una revisión anterior siga retenida.
- Preparar un realm independiente `uw-mcp-prod`, un usuario dedicado
  y un cliente de código `chatgpt-uw-prod` con PKCE S256, callback
  exacto de ChatGPT y solo `uw:read` como ámbito MCP. Preparar una
  credencial confidencial distinta para introspección y un enlace
  local de solo lectura al sitio correcto. Separar persistencia y
  credenciales de las de staging. Verificar coincidencia exacta
  de emisor, audiencia, sujeto y cliente. Crear secretos solo en
  el entorno administrativo autorizado. La rama no contiene valores.
- La primera opción de red usa el host CMS existente, sin DNS nuevo.
  En origen, definir ubicaciones exactas para `/mcp/chatgpt` y
  `/.well-known/oauth-protected-resource/mcp/chatgpt`. Ubicar
  el realm en un prefijo aislado y permitir explícitamente el
  descubrimiento, el flujo OIDC y sus recursos; conservar cerrados
  administración de Keycloak, realm master y el MCP nativo.
  Revisar con el administrador qué rutas exactas quedarían fuera
  del login interactivo de Access. Solo el endpoint MCP debe
  aceptar el Bearer propio del recurso. Mantener la política del
  panel y el rechazo por defecto en el resto del host. Confirmar
  el diseño con una prueba aislada y autorización antes de aplicar
  cualquier excepción de Access.

#### Desactivación y vuelta atrás

Conservar la configuración anterior y establecer una vía de
desactivación inmediata: poner `chatgpt_mcp.enabled=false` en el
config privado, cerrar las rutas específicas que se hubieran
habilitado, recargar el servicio afectado y revocar la concesión
productiva. Verificar que el MCP deja de responder a tokens válidos,
que el panel sigue protegido por Access y que la portada pública
sigue disponible. Volver al árbol anterior si falla la versión del
CMS. Restaurar SQLite solo ante una incidencia de datos y con la
copia verificada. Usar el rollback de Pages únicamente si la web
estática se vio afectada. La primera prueba MCP no ejecuta Wrangler.
