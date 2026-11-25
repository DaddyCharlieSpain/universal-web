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

$call = static fn(string $name, array $args, bool $write = true, bool $media = false): array => mcp_chatgpt_dispatch([
    'jsonrpc' => '2.0', 'id' => 1, 'method' => 'tools/call',
    'params' => ['name' => $name, 'arguments' => $args],
], $write, $media);

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
$image = imagecreatetruecolor(16, 16);
ob_start();
imagepng($image);
$png = ob_get_clean();
$args = ['filename' => 'synthetic.png', 'data_base64' => base64_encode($png), 'alt' => 'Synthetic square'];
expect(isset($call('draft_image_upload', $args)['error']), 'Draft scope alone cannot upload');
foreach ([
    ['filename' => 'fake.jpg'], ['filename' => 'fake.svg'],
    ['data_base64' => base64_encode(str_repeat('x', 32769))],
] as $invalid) {
    expect(isset($call('draft_image_upload', $invalid + $args, false, true)['error']), 'Reject invalid image');
}
$media = $call('draft_image_upload', $args, false, true)['result']['structuredContent']['media'] ?? [];
expect(($media['mime'] ?? null) === 'image/png', 'Image stored with independent scope');
$attach = ['id' => (int) $draft['id'], 'media_id' => (int) $media['id']];
expect(isset($call('draft_cover_set', $attach, false, true)['error']), 'Media scope alone cannot edit drafts');
expect(isset($call('draft_cover_set', $attach + ['status' => 'published'], true, true)['error']), 'Reject publication parameter');
expect(isset($call('draft_cover_set', ['id' => (int) $published['id']] + $attach, true, true)['error']), 'Published cover cannot change');
expect(isset($call('draft_cover_set', ['media_id' => PHP_INT_MAX] + $attach, true, true)['error']), 'Reject unknown image');
$cover = $call('draft_cover_set', $attach, true, true)['result']['structuredContent']['post'] ?? [];
expect(($cover['cover_image'] ?? null) === $media['url'] && $cover['status'] === 'draft', 'Draft cover persisted');
expect($beforePublic === row('SELECT * FROM posts WHERE id = ?', [$published['id']]), 'Published record unchanged after media operations');
expect($beforePublish === row('SELECT * FROM site_publish WHERE site_id = ?', [$siteId]), 'Publisher row unchanged after media operations');
expect((int) val("SELECT COUNT(*) FROM audit_log WHERE site_id = ? AND action = 'mcp.draft.media.upload'", [$siteId]) === 1, 'Media audit recorded');
expect(db()->query('PRAGMA integrity_check')->fetchAll(PDO::FETCH_COLUMN) === ['ok'], 'SQLite integrity');
expect(db()->query('PRAGMA foreign_key_check')->fetchAll() === [], 'SQLite foreign keys');
if (is_file(UW_PUBLIC . $media['url'])) unlink(UW_PUBLIC . $media['url']);
echo "MCP isolated draft and media workflow OK\n";
