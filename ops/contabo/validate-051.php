<?php
declare(strict_types=1);

const STAGING = '/opt/universal-web/staging/carlosbarcelo-051';
const RELEASE = '/opt/universal-web/releases/0.5.1';
const BACKUPS = '/var/backups/universal-web';
const EXPECTED_SCHEMA = 15;

final class ValidationError extends RuntimeException {}

function requireCheck(bool $ok, string $message): void
{
    if (!$ok) {
        throw new ValidationError($message);
    }
}

function openDatabase(string $path): SQLite3
{
    requireCheck(realpath($path) === $path && is_file($path), 'SQLite ausente o ruta enlazada');
    $db = new SQLite3($path, SQLITE3_OPEN_READONLY);
    $db->enableExceptions(true);
    $db->busyTimeout(5000);
    return $db;
}

function databaseChecks(SQLite3 $db): array
{
    requireCheck($db->querySingle('PRAGMA integrity_check') === 'ok', 'Integridad SQLite incorrecta');
    requireCheck($db->querySingle('PRAGMA foreign_key_check') === null, 'Referencias SQLite no válidas');
    requireCheck((string) $db->querySingle("SELECT value FROM meta WHERE key = 'schema_version'") === (string) EXPECTED_SCHEMA, 'Esquema SQLite inesperado');
    foreach (['pages', 'posts'] as $table) {
        $columns = [];
        $result = $db->query("PRAGMA table_info($table)");
        while ($column = $result->fetchArray(SQLITE3_ASSOC)) {
            $columns[] = $column['name'];
        }
        $result->finalize();
        $missing = array_diff(['path', 'content_at'], $columns);
        requireCheck($missing === [], "Esquema 15 incompleto en $table: " . implode(', ', $missing));
    }
    $counts = [];
    foreach (['sites', 'pages', 'posts', 'media', 'users', 'site_domains'] as $table) {
        $counts[$table] = $db->querySingle("SELECT count(*) FROM $table");
    }
    return $counts;
}

function stagingChecks(SQLite3 $db): void
{
    $siteId = (int) $db->querySingle("SELECT id FROM sites WHERE slug = 'carlos-barcelo-serrabona' AND theme = 'carlosbarcelo'");
    requireCheck($siteId > 0, 'Sitio o tema de staging incorrecto');
    $theme = STAGING . '/themes/carlosbarcelo';
    requireCheck(realpath($theme) === $theme && is_file($theme . '/layout.php'), 'Tema personalizado incompleto');
    $media = STAGING . '/public/media';
    requireCheck(realpath($media) === $media && is_dir($media), 'Directorio multimedia ausente o enlazado');
    $files = $db->query("SELECT path FROM media WHERE site_id = $siteId");
    while ($row = $files->fetchArray(SQLITE3_NUM)) {
        $path = realpath($media . '/' . $row[0]);
        requireCheck($path !== false && str_starts_with($path, $media . '/') && is_file($path) && is_readable($path), 'Falta un archivo multimedia o queda fuera de staging');
    }
    echo "staging=OK schema=15\n";
}

function testDatabase(SQLite3 $source, array $counts): void
{
    $dir = '/tmp/uw-051-' . bin2hex(random_bytes(16));
    requireCheck(mkdir($dir, 0700), 'No se pudo crear el aislamiento temporal');
    $path = $dir . '/universal.sqlite';
    try {
        $snapshot = new SQLite3($path);
        $snapshot->enableExceptions(true);
        try {
            requireCheck($source->backup($snapshot), 'No se pudo copiar SQLite');
        } finally {
            $snapshot->close();
        }

        // El núcleo de la release ejecuta la misma comprobación que bootstrap.
        // UW_DATA apunta solo a la copia. No se carga config.php ni se arranca publicación.
        $core = RELEASE . '/app/core.php';
        requireCheck(realpath($core) === $core && is_file($core), 'Núcleo de la release ausente o enlazado');
        define('UW_DATA', $dir);
        require $core;
        requireCheck(UW_VERSION === '0.5.1' && UW_SCHEMA === EXPECTED_SCHEMA, 'Release incompatible');
        ensure_schema();

        $result = openDatabase($path);
        try {
            requireCheck(databaseChecks($result) === $counts, 'Recuentos SQLite distintos tras la prueba');
        } finally {
            $result->close();
        }
        echo "test=OK version=0.5.1 schema=15\n";
    } finally {
        foreach (['', '-wal', '-shm', '-journal'] as $suffix) {
            if (is_file($path . $suffix)) {
                unlink($path . $suffix);
            }
        }
        rmdir($dir);
    }
}

function backupStatus(): void
{
    $status = trim((string) file_get_contents(BACKUPS . '/backup-status'));
    $last = trim((string) file_get_contents(BACKUPS . '/last-success'));
    if (preg_match('/^\d{10}$/D', $last)) {
        $timestamp = (int) $last;
    } elseif (preg_match('/^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})$/D', $last, $parts)) {
        $timestamp = strtotime("$parts[1] $parts[2]:$parts[3]:$parts[4]");
    } else {
        $timestamp = $last !== '' ? strtotime($last) : false;
    }
    requireCheck($timestamp !== false && $timestamp > 0 && $timestamp <= time(), 'Último éxito ausente o fecha incorrecta');
    echo 'backup_status=' . ($status === 'OK' ? 'OK' : 'ERROR') . "\n";
    echo 'last_success=' . gmdate(DATE_ATOM, $timestamp) . "\n";
    foreach (['backup.log', 'watchdog.log'] as $log) {
        $mtime = is_file(BACKUPS . '/' . $log) ? filemtime(BACKUPS . '/' . $log) : false;
        echo $log . '_mtime=' . ($mtime === false ? 'unavailable' : gmdate(DATE_ATOM, $mtime)) . "\n";
    }
    requireCheck($status === 'OK' && time() - $timestamp <= 26 * 3600, 'Copia con error o antigüedad superior a 26 horas');
}

if (PHP_SAPI !== 'cli' || $argc !== 2 || !in_array($argv[1], ['validate-051', 'test-051', 'backup-status'], true)) {
    exit(64);
}

ini_set('display_errors', '0');
ini_set('log_errors', '0');
date_default_timezone_set('Europe/Madrid');

try {
    if ($argv[1] === 'backup-status') {
        backupStatus();
    } else {
        $source = openDatabase(STAGING . '/data/universal.sqlite');
        try {
            $source->exec('BEGIN');
            $counts = databaseChecks($source);
            stagingChecks($source);
            if ($argv[1] === 'test-051') {
                testDatabase($source, $counts);
            }
        } finally {
            $source->close();
        }
    }
} catch (Throwable $error) {
    // Los errores de PHP y SQLite pueden incluir datos privados.
    $message = $error instanceof ValidationError
        ? $error->getMessage()
        : 'Fallo de ejecución en el servidor';
    fwrite(STDERR, $message . "\n");
    exit(1);
}
