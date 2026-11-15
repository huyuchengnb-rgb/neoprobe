"""自动挤服：盯住一台满员服务器，一有空位就自动启动游戏并进服。

原启动器的做法是 1 秒定时器 + 每 5 秒查一次（3 秒超时、1 次采样），
一旦发现人数 < 上限就立刻拉起游戏。这里保留同样的语义，但补了三处：

  * 探测前先复核：连续两次都读到空位才进（原版据一次采样就启动，
    等游戏起来空位往往已经被别人占了）
  * 探测走短超时 + 短重试，失败只是本轮跳过，不会把"探测失败"当成"有空位"
  * 全程记录人数变化，面板上能看到"到底有没有人在掉"
"""

from __future__ import annotations

import threading
import time
from typing import Any

from . import a2s, launch

# 原启动器的预留位提示：70 人上限、人数到 62 时会提醒普通用户可能挤不进去
RESERVED_MAX = 70
RESERVED_NEAR = 62


class QueueWatcher:
    """一台服务器的排队监视器（线程内循环，一个实例对应一次排队）。"""

    def __init__(self, address: str, label: str = "", interval: float = 3.0,
                 timeout: float = 2.0, retries: int = 2, gmod_path: str = "",
                 dry_run: bool = False) -> None:
        addr = a2s.parse_address(address)          # 非法地址抛 ValueError
        self.address = str(addr)
        self.key = addr.key
        self._addr = addr
        self.label = label or str(addr)
        self.interval = max(1.0, float(interval))
        self.timeout = max(0.5, float(timeout))
        self.retries = max(1, int(retries))
        self.gmod_path = gmod_path
        self.dry_run = dry_run

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._status = "watching"                  # watching|launched|cancelled|failed
        self._started_at = time.time()
        self._last_probe_at = 0.0
        self._attempts = 0
        self._players: int | None = None
        self._max_players: int | None = None
        self._last_error: str | None = None
        self._message = "已开始监视，等待空位"
        self._result: dict[str, Any] | None = None
        self._history: list[list[float]] = []      # [ts, players]
        self._drops = 0                            # 人数下降次数
        self.revision = 0                          # 供 /api/state 判断是否需要重新序列化

    # ------------------------------------------------------------ 生命周期

    def start(self) -> "QueueWatcher":
        if self._thread and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self._loop, name=f"queue-{self.key}",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self, reason: str = "已取消排队") -> None:
        self._stop.set()
        with self._lock:
            self.revision += 1
            if self._status == "watching":
                self._status = "cancelled"
                self._message = reason

    @property
    def active(self) -> bool:
        with self._lock:
            return self._status == "watching"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "active": self._status == "watching",
                "status": self._status,
                "address": self.address,
                "label": self.label,
                "started_at": self._started_at,
                "elapsed": round(now - self._started_at, 1),
                "interval": self.interval,
                "attempts": self._attempts,
                "players": self._players,
                "max_players": self._max_players,
                "has_slot": self._has_slot(),
                "reserved": self._reserved_hint(),
                "drops": self._drops,
                "last_probe_at": self._last_probe_at,
                "last_error": self._last_error,
                "message": self._message,
                "result": self._result,
                "history": list(self._history[-40:]),
                "dry_run": self.dry_run,
            }

    # ------------------------------------------------------------ 内部

    def _has_slot(self) -> bool:
        if self._players is None or not self._max_players:
            return False
        return self._players < self._max_players

    def _reserved_hint(self) -> bool:
        return bool(self._max_players and self._max_players >= RESERVED_MAX
                    and self._players is not None and self._players >= RESERVED_NEAR)

    def _probe(self) -> dict | None:
        last: Exception | None = None
        for attempt in range(self.retries):
            if self._stop.is_set():
                return None
            try:
                return a2s.query_info(self._addr, self.timeout, 1)
            except (a2s.A2SError, OSError) as exc:
                last = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.2)
        with self._lock:
            self._last_error = str(last) if last else None
        return None

    def _record(self, info: dict) -> None:
        players = info.get("players")
        max_players = info.get("max_players")
        with self._lock:
            self.revision += 1
            if (self._players is not None and isinstance(players, int)
                    and players < self._players):
                self._drops += 1
            self._players = players if isinstance(players, int) else None
            self._max_players = max_players if isinstance(max_players, int) else None
            self._attempts += 1
            self._last_probe_at = time.time()
            self._last_error = None
            self._history.append([round(self._last_probe_at, 1), self._players or 0])
            del self._history[:-60]
            if self._has_slot():
                self._message = f"检测到空位 {self._players}/{self._max_players}，正在确认"
            else:
                self._message = (f"服务器已满 {self._players}/{self._max_players}，继续等待"
                                 if self._max_players else "等待服务器数据")
                if self._reserved_hint():
                    self._message += "（该服有预留位，普通玩家可能挤不进）"

    def _loop(self) -> None:
        # 第一轮立刻探测：用户在"满员"和"有空位"之间点到时，不该白等一个间隔
        while not self._stop.is_set():
            info = self._probe()
            if self._stop.is_set():
                return
            if info is None:
                with self._lock:
                    self._attempts += 1
                    self._last_probe_at = time.time()
                    self._message = "探测失败，稍后重试"
            else:
                self._record(info)
                if self._has_slot() and self._confirm_slot():
                    self._do_launch()
                    return
            if self._stop.wait(self.interval):
                return

    def _confirm_slot(self) -> bool:
        """复核：空位消息可能已经过期，隔 300ms 再读一次。"""
        time.sleep(0.3)
        if self._stop.is_set():
            return False
        info = self._probe()
        if not info:
            return False
        self._record(info)
        return self._has_slot()

    def _do_launch(self) -> None:
        with self._lock:
            if self._status != "watching":
                return
            self._status = "launched"
            self._message = "抢到空位，正在启动游戏"
        result = launch.launch(self.address, self.gmod_path, dry_run=self.dry_run)
        with self._lock:
            self.revision += 1
            self._result = result
            if result.get("ok"):
                self._status = "launched"
                self._message = result.get("message") or "已启动"
            else:
                self._status = "failed"
                self._message = result.get("error") or "启动失败"
