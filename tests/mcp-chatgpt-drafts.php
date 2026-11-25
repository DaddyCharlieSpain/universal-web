<?php
declare(strict_types=1);

// Run only against a fresh temporary data directory.
$data = getenv('UW_DATA');
if (PHP_SAPI !== 'cli' || !$data || !is_dir($data) || count(scandir($data)) !== 2) {
    throw new RuntimeException('Set UW_DATA to a fresh empty test directory.');
}
require dirname(__DIR__) . '/app/bootstrap.php';

function expect(bool $ok, string $label): void
{
    if (!$ok) throw new RuntimeException($label);
}

$installed = uw_install([
    'site_name' => 'Universal Web MCP Lab', 'domain' => 'localhost',
    'admin_name' => 'MCP Test', 'admin_email' => 'mcp-test@example.invalid',
    'admin_password' => bin2hex(random_bytes(20)), 'timezone' => 'UTC',
]);
$site = $installed['site'];
$siteId = (int) $site['id'];
$svc = new SiteService($site);
McpContext::$token = ['site_id' => $siteId, 'scopes' => ['read'], 'owner_role' => 'editor'];
Actor::set('token', 1, 'MCP draft test');
$published = $svc->savePost(['title' => 'Published fixture']);
q("UPDATE posts SET status = 'published', published_at = ? WHERE id = ?", [now(), $published['id']]);
$previous = $svc->savePost(['title' => 'Previously published fixture']);
$old = row('SELECT * FROM posts WHERE id = ?', [$previous['id']]);
history_snapshot($siteId, 'post', array_replace($old, ['status' => 'published']));
q("INSERT INTO site_publish (site_id, config, dirty) VALUES (?, ?, 0)
    ON CONFLICT(site_id) DO UPDATE SET config = excluded.config, dirty = 0",
    [$siteId, json_enc(['mode' => 'static', 'auto_publish' => true, 'target' => 'download'])]);
$beforePublish = row('SELECT * FROM site_publish WHERE site_id = ?', [$siteId]);
$beforePublic = row('SELECT * FROM posts WHERE id = ?', [$published['id']]);

$call = static fn(string $name, array $args, bool $write = true): array => mcp_chatgpt_dispatch([
    'jsonrpc' => '2.0', 'id' => 1, 'method' => 'tools/call',
    'params' => ['name' => $name, 'arguments' => $args],
], $write);

expect(isset($call('draft_create', ['title' => 'Blocked'], false)['error']), 'Read token rejected');
$create = $call('draft_create', ['title' => 'Synthetic draft', 'content' => 'Test content',
    'seo' => ['title' => 'Synthetic SEO', 'description' => 'A synthetic description']]);
$draft = $create['result']['structuredContent']['post'] ?? null;
expect($draft && $draft['status'] === 'draft' && $draft['published_at'] === null, 'Draft created');
$edit = $call('draft_update', ['id' => (int) $draft['id'], 'seo' => ['noindex' => true]]);
$post = $edit['result']['structuredContent']['post'] ?? [];
expect(($post['seo']['title'] ?? null) === 'Synthetic SEO' && $post['seo']['noindex'] === true, 'Partial SEO update');
expect($post['content'] === 'Test content', 'Content survives SEO-only update');
expect(isset($call('draft_create', ['title' => 'Synthetic draft'])['error']), 'Duplicate create rejected');
foreach ([$published, $previous] as $fixture) {
    expect(isset($call('draft_update', ['id' => (int) $fixture['id'], 'title' => 'Changed'])['error']), 'Published content rejected');
}
expect(isset($call('draft_update', ['id' => (int) $draft['id'], 'status' => 'published'])['error']), 'Publication rejected');
expect(isset($call('post_delete', ['id' => (int) $draft['id']])['error']), 'Deletion rejected');
expect($beforePublic === row('SELECT * FROM posts WHERE id = ?', [$published['id']]), 'Published record unchanged');
expect($beforePublish === row('SELECT * FROM site_publish WHERE site_id = ?', [$siteId]), 'Static publication row unchanged');
expect((int) val("SELECT COUNT(*) FROM audit_log WHERE site_id = ? AND action IN ('mcp.draft.create', 'mcp.draft.update')", [$siteId]) === 2, 'Two audited writes');
echo "MCP isolated draft workflow OK\n";
