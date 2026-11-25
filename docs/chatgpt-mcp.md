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

Antes de dar por cerrado el laboratorio, comprobar en Cloudflare que
el token del túnel que se compartió accidentalmente fue invalidado
y que solo permanece conectado el conector autorizado. La prueba HTTP
no acredita la rotación. El despliegue MCP en producción requiere
autorización específica.
