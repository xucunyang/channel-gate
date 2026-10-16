# -*- coding: utf-8 -*-
"""gate：渠道访问治理闸门（单写者锁 + 日预算 + 拟人节奏 三合一）。

设计原则（对应全局规则「外部渠道访问治理」）：
    R1 单写者：同一渠道任一时刻只允许一个进程/任务在打（锁文件，机器级语义：
       默认 ~/.channel_gate/locks/，不管哪个项目发起，同渠道同刻只能一个任务）
    R2 日预算：先查后花，超了 fail-closed 拒发（台账 ~/.channel_gate/budget/，按日归零）
    R4 拟人节奏：随机间隔 + 连发 N 发强制批间休息（内部组合 pace.Pacer）

用法（驱动脚本标准姿势）：
    from channel_gate import ChannelGate

    gate = ChannelGate("my_channel", budget=60)
    with gate.session("某某采集"):        # 拿单写者锁；被占则报持有者信息
        for url in anchors:
            gate.wait()                    # 拟人间隔 + 批间休息
            if not gate.spend(1, url):     # 预算扣减，超了拒发（fail-closed）
                print("今日预算已尽，停发")
                break
            fetch(url)

只想要节奏不要锁/预算 → 直接用 channel_gate.Pacer。
状态目录可用环境变量 CHANNEL_STATE_DIR 重定向（测试/多机场景）。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from .pace import PRESETS, Pacer


class LockHeld(RuntimeError):
    """渠道单写者锁被别的进程持有。"""

    def __init__(self, channel: str, holder: dict):
        self.holder = holder
        super().__init__(
            f"[{channel}] 单写者锁被占：pid={holder.get('pid')} 任务={holder.get('purpose')!r} "
            f"自 {holder.get('started_at')}\n"
            f"  → 等对方跑完销号；确认对方进程已死可强制接管："
            f"channel-gate release {channel} --force")


class BudgetExhausted(RuntimeError):
    """日预算已尽（fail-closed，拒发）。"""


# ---------- 状态目录 ----------

def _state_dir() -> Path:
    env = os.environ.get("CHANNEL_STATE_DIR")
    return Path(env) if env else Path.home() / ".channel_gate"


def lock_path(channel: str) -> Path:
    return _state_dir() / "locks" / f"{channel}.lock"


def budget_path(channel: str, day: str | None = None) -> Path:
    day = day or time.strftime("%Y-%m-%d")
    return _state_dir() / "budget" / f"{channel}.{day}.json"


# ---------- 锁原语 ----------

def _pid_alive(pid: int) -> bool:
    pid = int(pid)
    if pid <= 0:
        return False
    if os.name == "nt":
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        k.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_lock(channel: str) -> dict | None:
    p = lock_path(channel)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"pid": -1, "purpose": "<锁文件损坏>", "started_at": "?"}


def acquire(channel: str, purpose: str, force: bool = False) -> dict:
    """取单写者锁。同 pid 可重入；持锁进程已死自动抢占；活进程则报 LockHeld。"""
    cur = _read_lock(channel)
    if cur and not force:
        pid = int(cur.get("pid", -1))
        if _pid_alive(pid):
            if pid == os.getpid():
                return cur  # 同进程重入
            raise LockHeld(channel, cur)
        print(f"[{channel}] 抢占过期锁（pid {pid} 已死，原任务 {cur.get('purpose')!r}）")
    holder = {"pid": os.getpid(), "channel": channel, "purpose": purpose,
              "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    p = lock_path(channel)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(holder, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    print(f"[{channel}] 单写者锁已取（{purpose}）。跑前登记任务台账，跑完销号释放。")
    return holder


def release(channel: str, force: bool = False) -> bool:
    """释放锁。默认只放自己进程的；--force 强制（仅确认对方真死后用）。"""
    cur = _read_lock(channel)
    if not cur:
        return False
    if not force and int(cur.get("pid", -1)) != os.getpid():
        print(f"[{channel}] 锁属于 pid {cur.get('pid')}（{cur.get('purpose')!r}），非本进程，拒绝释放")
        return False
    lock_path(channel).unlink(missing_ok=True)
    print(f"[{channel}] 锁已释放")
    return True


@contextmanager
def lock(channel: str, purpose: str, force: bool = False):
    acquire(channel, purpose, force=force)
    try:
        yield
    finally:
        release(channel)


# ---------- 日预算台账 ----------

def spent_today(channel: str, day: str | None = None) -> int:
    p = budget_path(channel, day)
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("spent", 0))
    except Exception:
        return 0


# ---------- 闸门 ----------

class ChannelGate:
    """一把闸门管一个渠道：session() 取锁，wait() 节奏，spend() 扣预算。"""

    def __init__(self, channel: str, budget: int | None = None,
                 pace: tuple[float, float] = (3, 8),
                 pause_every: int = 10, pause_range: tuple[float, float] = (300, 600),
                 log=None):
        self.channel = channel
        self.budget = budget
        if channel in PRESETS:
            self.pacer = Pacer.for_channel(channel)
        else:
            self.pacer = Pacer(*pace, pause_every=pause_every,
                               pause_range=pause_range, name=channel)
        self._log = log or print

    # -- 锁 --
    @contextmanager
    def session(self, purpose: str, force: bool = False):
        with lock(self.channel, purpose, force=force):
            if self.budget is not None:
                self._log(f"[{self.channel}] 今日预算 {self.spent()}/{self.budget}"
                          f"（余 {self.remaining()}）")
                if self.remaining() <= 0:
                    raise BudgetExhausted(
                        f"[{self.channel}] 日预算已用尽（{self.spent()}/{self.budget}），"
                        f"fail-closed 拒发。明天再来或调预算。")
            yield self

    # -- 节奏 --
    def wait(self) -> float:
        return self.pacer.wait()

    # -- 预算 --
    def spend(self, n: int = 1, note: str = "") -> bool:
        """扣减预算。返回 False = 预算已尽（调用方必须停发）。"""
        spent = spent_today(self.channel) + n
        if self.budget is not None and spent > self.budget:
            self._log(f"[{self.channel}] ⛔ 预算拒发：已用 {spent - n}，"
                      f"本笔将超 {self.budget}（{note}）")
            return False
        p = budget_path(self.channel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"spent": spent, "last_note": note,
                                 "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                                ensure_ascii=False), encoding="utf-8")
        if self.budget is not None and spent >= self.budget:
            self._log(f"[{self.channel}] 今日预算已用满（{spent}/{self.budget}）")
        return True

    def spent(self) -> int:
        return spent_today(self.channel)

    def remaining(self) -> int | None:
        return None if self.budget is None else max(0, self.budget - self.spent())


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="channel-gate", description="渠道单写者锁/预算查看")
    ap.add_argument("cmd", choices=["status", "release", "budget"])
    ap.add_argument("channel")
    ap.add_argument("--force", action="store_true", help="release：强制接管")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        s = _read_lock(a.channel)
        print(json.dumps(s, ensure_ascii=False, indent=1) if s else f"[{a.channel}] 无锁，渠道空闲")
        return 0
    if a.cmd == "budget":
        print(f"[{a.channel}] 今日已用 {spent_today(a.channel)} 发")
        return 0
    return 0 if release(a.channel, force=a.force) else 2


if __name__ == "__main__":
    sys.exit(main())
