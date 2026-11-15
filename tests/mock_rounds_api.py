"""本地假的 status.php，用于在没有真实回合数据时验证 UI / 解析。

    python tests/mock_rounds_api.py 8799

每次请求都会让 round_time_left 递减，并给出正确的 updated_at/server_time，
这样能验证"服务端时间差补偿 + 前端本地走秒"这条链路。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = time.time()
ROUND_LEN = 300.0

SERVERS = [
    # ip, port, name, rounds_left, offset(秒)  负数表示该服不在对局中
    ("43.249.193.77", 27076, "[CN]Neo RXBreach mio服①服", 3, 0),
    ("202.189.23.252", 27045, "[CN]Neo RXBreach mio服④服", 1, 120),
    ("202.189.21.228", 27265, "[CN]Neo RXBreach mio服白菜测试服", -1, -1),
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        now = int(time.time())
        elapsed = time.time() - START
        servers = []
        for ip, port, name, rounds_left, offset in SERVERS:
            if offset < 0:
                left = -1
                phase = "空闲"
            else:
                left = int(max(0, ROUND_LEN - ((elapsed + offset) % ROUND_LEN)))
                if left == 0:
                    phase = "回合结束"
                elif left < 20:
                    phase = "核弹倒计时"
                else:
                    phase = "回合中"
            servers.append({
                "server_name": name,
                "ip": ip,
                "port": port,
                "rounds_left": rounds_left,
                "round_time_left": left,
                "round_phase": phase,
                "updated_at": now - 2,   # 故意给 2 秒延迟，验证补偿逻辑
            })
        body = json.dumps({"server_time": now, "servers": servers},
                          ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock status.php -> http://127.0.0.1:{port}/status.php")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
