<?php
declare(strict_types=1);

const MCP_CHATGPT_MEDIA_SCOPE = 'uw:drafts:media';
const MCP_CHATGPT_IMAGE_MAX_BYTES = 32768;

function mcp_chatgpt_media_tool(bool $attach): array
{
    $int = ['type' => 'integer', 'minimum' => 1];
    $string = ['type' => 'string'];
    $properties = $attach ? ['id' => $int, 'media_id' => $int]
        : ['filename' => $string, 'data_base64' => $string, 'alt' => $string];
    $scopes = [MCP_CHATGPT_SCOPE, MCP_CHATGPT_MEDIA_SCOPE];
    if ($attach) $scopes[] = MCP_CHATGPT_DRAFT_SCOPE;
    return [
        'name' => $attach ? 'draft_cover_set' : 'draft_image_upload',
        'description' => $attach
            ? 'Asigna por ID una imagen del mismo laboratorio a un borrador nunca publicado.'
            : 'Sube una imagen sintética PNG o JPEG en base64 puro, hasta 32 KiB y 1024 × 1024 píxeles.',
        'inputSchema' => ['type' => 'object', 'properties' => $properties,
            'required' => array_keys($properties), 'additionalProperties' => false],
        'annotations' => ['readOnlyHint' => false, 'destructiveHint' => false,
            'idempotentHint' => false, 'openWorldHint' => false],
        'securitySchemes' => [['type' => 'oauth2', 'scopes' => $scopes]],
    ];
}

function mcp_chatgpt_image_upload(SiteService $svc, array $args): array
{
    $filename = $args['filename'];
    $alt = trim($args['alt']);
    if (!preg_match('/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}\.(png|jpe?g)$/iD', $filename, $match)
        || $alt === '' || strlen($alt) > 500) {
        throw new UwError('Indica un nombre PNG/JPEG simple y texto alternativo.');
    }
    $b64 = $args['data_base64'];
    if (strlen($b64) > 4 * (int) ceil(MCP_CHATGPT_IMAGE_MAX_BYTES / 3)
        || !preg_match('/^[A-Za-z0-9+\/]+={0,2}$/D', $b64)) {
        throw new UwError('Imagen base64 inválida o demasiado grande.');
    }
    $binary = base64_decode($b64, true);
    $info = $binary !== false ? @getimagesizefromstring($binary) : false;
    $png = strtolower($match[1]) === 'png';
    if (!$info || strlen($binary) > MCP_CHATGPT_IMAGE_MAX_BYTES
        || $info[2] !== ($png ? IMAGETYPE_PNG : IMAGETYPE_JPEG)
        || min($info[0], $info[1]) < 1 || max($info[0], $info[1]) > 1024) {
        throw new UwError('Imagen inválida, formato incorrecto o límite superado.');
    }
    if (!function_exists('imagecreatefromstring') || !function_exists($png ? 'imagepng' : 'imagejpeg')) {
        throw new UwError('GD no admite este formato en staging.');
    }
    $image = @imagecreatefromstring($binary);
    if (!$image) throw new UwError('No se pudo decodificar la imagen.');
    $tmp = tempnam(sys_get_temp_dir(), 'uw-mcp-image-');
    if ($tmp === false) throw new UwError('No se pudo crear el archivo temporal.');
    try {
        if ($png) imagesavealpha($image, true);
        $saved = $png ? imagepng($image, $tmp) : imagejpeg($image, $tmp, 85);
        if (!$saved || filesize($tmp) > 524288) throw new UwError('La imagen normalizada supera el límite o no se pudo guardar.');
        $media = $svc->storeMedia($tmp, $filename, $alt, false, ['keep_original' => true], draftMedia: true);
        return array_intersect_key($media, array_flip(['id', 'url', 'mime', 'size', 'alt']));
    } finally {
        if (is_file($tmp)) unlink($tmp);
    }
}

function mcp_chatgpt_image_url(SiteService $svc, int $id): string
{
    $media = row("SELECT path, mime FROM media WHERE id = ? AND site_id = ? AND kind = 'image'", [$id, $svc->id()]);
    $path = $media['path'] ?? '';
    if (!preg_match('#^universal-web-mcp-lab/[0-9]{4}/[0-9]{2}/[A-Za-z0-9_-]+\.(png|jpe?g|webp)$#iD', $path)
        || !in_array($media['mime'], ['image/png', 'image/jpeg', 'image/webp'], true)) {
        throw new UwError('Imagen del laboratorio no encontrada.');
    }
    $root = UW_PUBLIC . '/media/';
    $file = $root . $path;
    if (realpath($file) !== $file || !is_file($file)) throw new UwError('Imagen local no disponible.');
    $info = @getimagesize($file);
    if (!$info || ($info['mime'] ?? null) !== $media['mime'] || filesize($file) > 524288
        || min($info[0], $info[1]) < 1 || max($info[0], $info[1]) > 1024) {
        throw new UwError('La imagen local supera los límites o tiene un formato inválido.');
    }
    return '/media/' . $path;
}
