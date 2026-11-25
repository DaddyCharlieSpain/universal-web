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
echo "MCP read-only contracts OK\n";
