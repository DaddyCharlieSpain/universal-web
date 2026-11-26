<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/mcp-chatgpt.php';

function expect(bool $condition, string $label): void
{
    if (!$condition) throw new RuntimeException($label);
}

function mcp_error(mixed $id, int $code, string $message): array
{
    return ['id' => $id, 'error' => ['code' => $code]];
}

function mcp_tools(): array
{
    return ['post_get' => ['scope' => 'read'], 'seo_audit' => ['scope' => 'read', 'writes' => true]];
}

function mcp_dispatch(array $request): array
{
    return ['id' => $request['id'], 'result' => (object) ['tools' => [
        ['name' => 'post_get', 'annotations' => ['readOnlyHint' => true]],
        ['name' => 'seo_audit', 'annotations' => ['readOnlyHint' => false]],
        ['name' => 'publish_now', 'annotations' => ['readOnlyHint' => false]],
    ]]];
}

$cfg = ['issuer' => 'https://issuer.example', 'subject' => 'editor', 'client_id' => 'chatgpt',
    'resource' => 'https://cms.example/mcp/chatgpt'];
$now = 1000;
$good = ['active' => true, 'iss' => $cfg['issuer'], 'sub' => $cfg['subject'],
    'client_id' => $cfg['client_id'], 'aud' => [$cfg['resource']], 'exp' => $now + 60, 'scope' => 'uw:read'];
expect(mcp_chatgpt_claims_allowed($cfg, $good, $now), 'Valid access token');
foreach (['active' => false, 'iss' => 'https://other.example', 'sub' => 'other', 'client_id' => 'other',
    'aud' => ['https://other.example'], 'exp' => $now, 'nbf' => $now + 1, 'scope' => 'uw:write'] as $key => $value) {
    expect(!mcp_chatgpt_claims_allowed($cfg, array_replace($good, [$key => $value]), $now), "Rejected claim: $key");
}
$rpc = ['jsonrpc' => '2.0', 'id' => 1];
$listed = mcp_chatgpt_dispatch($rpc + ['method' => 'tools/list'])['result']->tools;
expect(array_column($listed, 'name') === ['post_get'], 'Only allowed read tools are listed');
expect($listed[0]['securitySchemes'][0]['scopes'] === ['uw:read'], 'OAuth scope advertised');
foreach (['page_save', 'post_save', 'media_upload', 'publish_now', 'post_delete', 'seo_audit'] as $tool) {
    expect(isset(mcp_chatgpt_dispatch($rpc + ['method' => 'tools/call', 'params' => ['name' => $tool]])['error']), "Denied: $tool");
}
expect(isset(mcp_chatgpt_dispatch($rpc + ['method' => 'tools/call', 'params' => ['name' => 'post_get']])['result']), 'Allowed read');
expect(mcp_chatgpt_dispatch(['jsonrpc' => '2.0', 'method' => 'notifications/initialized']) === null, 'Notification accepted');
$writeList = mcp_chatgpt_dispatch($rpc + ['method' => 'tools/list'], true)['result']->tools;
expect(array_column($writeList, 'name') === ['post_get', 'draft_create', 'draft_update'], 'Draft catalog requires write scope');
$schema = $writeList[2]['inputSchema'];
expect($writeList[2]['securitySchemes'][0]['scopes'] === ['uw:read', 'uw:drafts:write'], 'Separate draft scope');
expect(mcp_chatgpt_validate_args(['id' => 4, 'seo' => ['noindex' => true]], $schema), 'SEO patch');
foreach ([
    ['id' => '4'], ['id' => 0], ['id' => 4, 'status' => 'published'], ['id' => 4, 'published_at' => 'tomorrow'],
    ['id' => 4, 'site' => 'other'], ['id' => 4, 'slug' => 'other'], ['id' => 4, 'seo' => ['image' => 'https://example.com/']],
    ['id' => 4, 'seo' => ['noindex' => 'true']],
] as $args) {
    expect(!mcp_chatgpt_validate_args($args, $schema), 'Reject malformed or forbidden draft parameter');
}
foreach (['draft_create', 'draft_update'] as $name) {
    expect(isset(mcp_chatgpt_dispatch($rpc + ['method' => 'tools/call', 'params' => ['name' => $name, 'arguments' => ['title' => 'Test']]])['error']), "Read scope rejects $name");
}
foreach (['post_save', 'post_delete', 'post_restore', 'publish_now', 'media_upload'] as $name) {
    expect(isset(mcp_chatgpt_dispatch($rpc + ['method' => 'tools/call', 'params' => ['name' => $name]], true)['error']), "Draft scope rejects $name");
}
echo "MCP read and draft contracts OK\n";
