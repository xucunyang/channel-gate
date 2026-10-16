# -*- coding: utf-8 -*-
"""channel_gate：渠道访问治理（单写者锁 + 日预算 + 拟人节奏）。

顶层导出：
    from channel_gate import ChannelGate, Pacer, PRESETS
    from channel_gate import LockHeld, BudgetExhausted, acquire, release, lock

模块布局：
    channel_gate.pace  纯拟人节奏器（无状态、可注入时钟，任何业务可单独用）
    channel_gate.gate  渠道治理闸门（锁 + 预算 + 节奏组合）与 CLI
"""
from .gate import (BudgetExhausted, ChannelGate, LockHeld,  # noqa: F401
                   acquire, budget_path, lock, lock_path, release,
                   spent_today)
from .pace import PRESETS, Pacer  # noqa: F401

__version__ = "0.1.0"

__all__ = [
    "Pacer", "PRESETS",
    "ChannelGate", "LockHeld", "BudgetExhausted",
    "acquire", "release", "lock", "lock_path", "spent_today", "budget_path",
    "__version__",
]
