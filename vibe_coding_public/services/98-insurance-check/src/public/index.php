<?php
declare(strict_types=1);
require __DIR__ . '/../vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

// Parse postgres:// DSN
$dsnStr = getenv('PG_DSN') ?: 'postgres://vibe:vibe@postgres:5432/vibe';
$parsed = parse_url($dsnStr);
$pdoDsn = sprintf('pgsql:host=%s;port=%d;dbname=%s',
    $parsed['host'],
    $parsed['port'] ?? 5432,
    ltrim($parsed['path'] ?? '/vibe', '/')
);
$pdoUser = $parsed['user'] ?? 'vibe';
$pdoPass = $parsed['pass'] ?? 'vibe';

$pdo = null;
try {
    $pdo = new PDO($pdoDsn, $pdoUser, $pdoPass, [
        PDO::ATTR_ERRMODE    => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_TIMEOUT    => 2,
    ]);
    $pdo->exec("CREATE TABLE IF NOT EXISTS eligibility_records(
        id serial PRIMARY KEY,
        patient_id text,
        insurance_id text,
        eligible bool DEFAULT false,
        checked_at timestamptz DEFAULT now()
    )");
} catch (Exception $e) {
    error_log('ERROR insurance-check: db init: ' . $e->getMessage());
}

$app = AppFactory::create();
$app->addBodyParsingMiddleware();
$app->addErrorMiddleware(false, false, false);

$app->get('/healthz', function (Request $req, Response $res): Response {
    $res->getBody()->write(json_encode(['status' => 'ok', 'service' => 'insurance-check']));
    return $res->withHeader('Content-Type', 'application/json');
});

$app->post('/eligibility', function (Request $req, Response $res) use ($pdo): Response {
    $body = (array) $req->getParsedBody();
    $patientId   = $body['patient_id'] ?? '';
    $insuranceId = $body['insurance_id'] ?? '';
    $eligible    = false;

    // Call upstream with 2s timeout
    try {
        $ctx = stream_context_create(['http' => [
            'method'  => 'POST',
            'header'  => "Content-Type: application/json\r\n",
            'content' => json_encode(['patient_id' => $patientId, 'insurance_id' => $insuranceId]),
            'timeout' => 2,
        ]]);
        $raw = @file_get_contents('http://mock-upstream:8080/verify', false, $ctx);
        if ($raw !== false) {
            $data     = json_decode($raw, true);
            $eligible = (bool) ($data['eligible'] ?? false);
        }
    } catch (Exception $e) {
        error_log('ERROR insurance-check: upstream failed: ' . $e->getMessage());
    }

    try {
        $stmt = $pdo->prepare(
            "INSERT INTO eligibility_records(patient_id,insurance_id,eligible) VALUES(?,?,?) " .
            "RETURNING id,patient_id,insurance_id,eligible,checked_at::text"
        );
        $stmt->execute([$patientId, $insuranceId, $eligible ? 'true' : 'false']);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        $res->getBody()->write(json_encode($row));
        return $res->withStatus(201)->withHeader('Content-Type', 'application/json');
    } catch (Exception $e) {
        error_log('ERROR insurance-check: ' . $e->getMessage());
        $res->getBody()->write(json_encode(['error' => 'db error']));
        return $res->withStatus(503)->withHeader('Content-Type', 'application/json');
    }
});

$app->get('/eligibility/{patient_id}', function (Request $req, Response $res, array $args) use ($pdo): Response {
    $patientId = $args['patient_id'];
    try {
        $stmt = $pdo->prepare(
            "SELECT id,patient_id,insurance_id,eligible,checked_at::text FROM eligibility_records WHERE patient_id=? ORDER BY checked_at DESC"
        );
        $stmt->execute([$patientId]);
        $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
        $res->getBody()->write(json_encode($rows));
        return $res->withHeader('Content-Type', 'application/json');
    } catch (Exception $e) {
        error_log('ERROR insurance-check: ' . $e->getMessage());
        $res->getBody()->write(json_encode(['error' => 'db error']));
        return $res->withStatus(503)->withHeader('Content-Type', 'application/json');
    }
});

$app->run();
