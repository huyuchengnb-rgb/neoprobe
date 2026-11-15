"""空位观测：为"挤服"提供可测量的依据。

挤服的人不在服务器里，所以拿不到客户端状态；而对挤服真正有用的信息不是"还剩几回合"，
而是"**什么时候会空出位置**"。这件事可以直接测：

  * 定时拉 A2S_PLAYER 的玩家名单，和上一轮对比
  * 名单里少掉的人 = 走了；多出来的人 = 进来了
  * 人数已经满时，只有靠名单差异才能发现"有人走、位置被瞬间补上"的空窗

于是可以得到：近 N 分钟空出过几次、平均多久一次、上一次是什么时候、
按节奏下次大概还有多久；以及"集体退服"（一局结束时常见）的观测周期。

两条红线：
  1. 只统计**观测到的事实**，不假设回合时长（br_time_round 是配置，不是节奏）
  2. 样本不足就说样本不足，不给一个"看起来精确"的数字
"""

from __future__ import annotations

import statistics
import time
from collections import deque


class SlotTracker:
    """一台服的空位观测器。线程安全由调用方（manager 的锁）保证。"""

    __slots__ = ("key", "address", "samples", "events", "started_at", "last_error",
                 "poll_ok", "poll_fail")

    def __init__(self, key: str, address: str, keep: int = 120) -> None:
        self.key = key
        self.address = address
        # (ts, frozenset(names))——只留最近若干轮，够算 30 分钟即可
        self.samples: deque = deque(maxlen=keep)
        # (ts, left, joined, players)
        self.events: deque = deque(maxlen=240)
        self.started_at = time.time()
        self.last_error: str | None = None
        self.poll_ok = 0
        self.poll_fail = 0

    # ------------------------------------------------------------ 采样

    def feed(self, ts: float, names: list[str], players: int) -> None:
        cur = frozenset(n for n in names if n)
        prev = self.samples[-1][1] if self.samples else None
        if prev is not None and cur:
            left = len(prev - cur)
            joined = len(cur - prev)
            if left or joined:
                self.events.append((ts, left, joined, players))
        self.samples.append((ts, cur))
        self.poll_ok += 1

    def fail(self, err: str) -> None:
        self.last_error = err
        self.poll_fail += 1

    # ------------------------------------------------------------ 统计

    def stats(self, now: float | None = None, window: float = 1800.0) -> dict | None:
        now = time.time() if now is None else now
        recent = [e for e in self.events if now - e[0] <= window]
        if not self.samples or (self.poll_ok < 2 and not recent):
            return None

        free = [e for e in recent if e[1] >= 1]
        freed_players = sum(e[1] for e in free)
        last_free = max((e[0] for e in free), default=None)

        # 相邻两次"有人走"的间隔；太长的间隔（隔夜）不计入节奏
        gaps: list[float] = []
        for prev, cur in zip(free, free[1:]):
            gap = cur[0] - prev[0]
            if 25 <= gap <= 3600:
                gaps.append(gap)
        avg_gap = statistics.fmean(gaps) if gaps else None
        eta = None
        if avg_gap and last_free:
            eta = avg_gap - (now - last_free)
            eta = max(0.0, min(eta, 3600.0))

        # 集体退服：一次观测里走了"明显偏多"的人，往往是一局结束
        burst_threshold = max(4, int(0.08 * max((e[3] for e in recent), default=0)))
        bursts = [e for e in recent if e[1] >= burst_threshold]
        burst_gaps = []
        for prev, cur in zip(bursts, bursts[1:]):
            gap = cur[0] - prev[0]
            if 120 <= gap <= 3600:
                burst_gaps.append(gap)
        burst_period = None
        if len(burst_gaps) >= 2:
            mean = statistics.fmean(burst_gaps)
            sd = statistics.pstdev(burst_gaps)
            # 只有节奏稳定（变异系数 < 0.45）才当成周期，否则宁可不给结论
            if mean > 0 and sd / mean < 0.45:
                burst_period = mean

        return {
            "window": int(window),
            "samples": self.poll_ok,
            "fails": self.poll_fail,
            "free_events": len(free),
            "freed_players": freed_players,
            "last_free_at": round(last_free, 1) if last_free else None,
            "since_last_free": round(now - last_free, 1) if last_free else None,
            "avg_gap": round(avg_gap, 1) if avg_gap else None,
            "eta": round(eta, 1) if eta is not None else None,
            "bursts": len(bursts),
            "burst_period": round(burst_period, 1) if burst_period else None,
            "last_burst_at": round(max((e[0] for e in bursts), default=0), 1) or None,
            "gap_samples": len(gaps),
            "since_start": max(0.0, round(now - self.started_at, 1)),
            "error": self.last_error,
        }

    def to_dict(self, now: float | None = None) -> dict | None:
        return self.stats(now)
