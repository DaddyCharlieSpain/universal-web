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
