<?php
/**
 * NeoProbe 回合接收端（PHP 单文件）
 *
 * 作用：收下各服 GMod 插件 POST 上来的回合状态，按 status.php 的格式吐给面板。
 * 面板「回合接口」填这个文件的地址即可（例如 https://你的域名/rounds.php）。
 *
 * 部署：丢到任意支持 PHP 的站点，确保同目录可写（会生成 rounds-data.json）。
 *      建议加一个随机路径或 secret，别让陌生人乱写。
 *
 * 写入（服务器插件 -> 这里）：
 *   POST /rounds.php  {"server_name":"...","ip":"1.2.3.4","port":27015,
 *                      "rounds_left":3,"round_time_left":245,
 *                      "round_phase":"回合中","updated_at":1794660000,"secret":"..."}
 *
 * 读取（面板 -> 这里）：
 *   GET  /rounds.php  {"server_time":1794660000,"servers":[...]}
 */

declare(strict_types=1);

const DATA_FILE = __DIR__ . '/rounds-data.json';
const STALE_SECONDS = 120;          // 超过 2 分钟没更新的服视为离线，不返回
const SECRET = '';                  // 与插件约定的 secret；留空表示不校验

function load(): array
{
    if (!is_file(DATA_FILE)) {
        return [];
    }
    $raw = @file_get_contents(DATA_FILE);
    $data = $raw ? json_decode($raw, true) : null;
    return is_array($data) ? $data : [];
}

function store(array $data): void
{
    $tmp = DATA_FILE . '.tmp';
    file_put_contents($tmp, json_encode($data, JSON_UNESCAPED_UNICODE), LOCK_EX);
    rename($tmp, DATA_FILE);        // 原子替换，读的一方不会读到半个文件
}

function reply(array $payload, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $body = file_get_contents('php://input');
    $in = json_decode($body ?: '', true);
    if (!is_array($in)) {
        reply(['error' => 'invalid json'], 400);
    }
    if (SECRET !== '' && (($in['secret'] ?? '') !== SECRET)) {
        reply(['error' => 'bad secret'], 403);
    }

    $ip = trim((string)($in['ip'] ?? ''));
    $port = (int)($in['port'] ?? 0);
    if ($ip === '' || $port <= 0 || $port > 65535) {
        reply(['error' => 'missing ip/port'], 400);
    }

    $num = static function ($v, int $min, int $max): int {
        if (!is_numeric($v)) {
            return -1;
        }
        $n = (int)$v;
        return ($n < $min || $n > $max) ? -1 : $n;
    };

    $key = $ip . ':' . $port;
    $data = load();
    $data[$key] = [
        'server_name'     => mb_substr((string)($in['server_name'] ?? $key), 0, 64),
        'ip'              => $ip,
        'port'            => $port,
        'rounds_left'     => $num($in['rounds_left'] ?? -1, 0, 999),
        'round_time_left' => $num($in['round_time_left'] ?? -1, 0, 86400),
        'round_phase'     => mb_substr((string)($in['round_phase'] ?? '未知'), 0, 16),
        'updated_at'      => time(),     // 用服务端时间，不信上报方的时钟
    ];
    store($data);
    reply(['ok' => true, 'key' => $key]);
}

// GET：只返回还活着的服
$now = time();
$servers = [];
foreach (load() as $row) {
    if (is_array($row) && isset($row['updated_at']) && ($now - (int)$row['updated_at']) <= STALE_SECONDS) {
        $servers[] = $row;
    }
}
usort($servers, static fn($a, $b) => strcmp((string)$a['ip'], (string)$b['ip']) ?: ($a['port'] <=> $b['port']));
reply(['server_time' => $now, 'servers' => $servers]);
