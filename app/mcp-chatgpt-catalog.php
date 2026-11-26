<?php
declare(strict_types=1);

function mcp_chatgpt_catalog_tools(): array
{
    $tools = [];
    foreach (['page_list', 'page_get', 'post_list', 'post_get'] as $name) {
        $get = str_ends_with($name, '_get');
        $article = str_starts_with($name, 'post_');
        $properties = ['lang' => ['type' => 'string']];
        if ($get) $properties['slug'] = ['type' => 'string'];
        if ($name === 'post_list') {
            $properties['limit'] = ['type' => 'integer', 'minimum' => 1, 'maximum' => 100];
            $properties['offset'] = ['type' => 'integer', 'minimum' => 0];
        }
        $tools[$name] = [
            'name' => $name,
            'description' => ($get ? 'Consulta' : 'Lista') . ($article ? ' artículos publicados' : ' páginas publicadas')
                . '. Devuelve título, slug, idioma y ruta pública.',
            'inputSchema' => ['type' => 'object', 'properties' => $properties,
                'required' => $get ? ['slug'] : [], 'additionalProperties' => false],
            'annotations' => ['readOnlyHint' => true],
            'securitySchemes' => [['type' => 'oauth2', 'scopes' => [MCP_CHATGPT_SCOPE]]],
        ];
    }
    return $tools;
}

function mcp_chatgpt_catalog_read(string $name, array $args): array
{
    $site = site_by_id((int) McpContext::$token['site_id']);
    if (!$site) throw new UwError('Sitio no disponible.');
    $svc = new SiteService($site);
    if (isset($args['lang'])) {
        if (!in_array($args['lang'], $svc->langs(), true)) throw new UwError('Idioma no disponible.');
        $svc->lang = $args['lang'];
    }
    $fields = array_flip(['slug', 'title', 'lang', 'public_path', 'published_at']);
    $summary = static fn(array $item): array => array_intersect_key($item, $fields);
    if ($name === 'page_list') return ['pages' => array_map($summary, $svc->pages(true))];
    if ($name === 'post_list') {
        $options = ['public' => true, 'limit' => $args['limit'] ?? 20, 'offset' => $args['offset'] ?? 0];
        return ['total' => $svc->countPosts($options), 'posts' => array_map($summary, $svc->posts($options))];
    }
    $article = $name === 'post_get';
    $item = $article ? $svc->post($args['slug']) : $svc->page($args['slug']);
    if (!$item || $item['status'] !== 'published'
        || ($article && (empty($item['published_at']) || $item['published_at'] > now()))) {
        throw new UwError('Contenido publicado no encontrado.');
    }
    return [$article ? 'post' : 'page' => $summary($item)];
}

function mcp_chatgpt_catalog_call(int|string $id, mixed $name, mixed $args): array
{
    $tool = is_string($name) ? (mcp_chatgpt_catalog_tools()[$name] ?? null) : null;
    if (!$tool || !is_array($args) || !mcp_chatgpt_validate_args($args, $tool['inputSchema'])) {
        return mcp_error($id, -32602, 'Catalog tool or arguments unavailable');
    }
    try {
        $result = mcp_chatgpt_catalog_read($name, $args);
        return ['jsonrpc' => '2.0', 'id' => $id, 'result' => [
            'content' => [['type' => 'text', 'text' => json_enc($result)]],
            'structuredContent' => $result, 'isError' => false,
        ]];
    } catch (UwError $error) {
        return mcp_error($id, -32602, $error->getMessage());
    } catch (Throwable $error) {
        error_log('[universal-web mcp catalog] ' . $error::class);
        return mcp_error($id, -32603, 'Catalog read failed');
    }
}
