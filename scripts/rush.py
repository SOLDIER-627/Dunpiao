#!/usr/bin/env python
"""抢票模式（开售）——详情页待命 → T0 直点 → 订单页核对 →（--submit）提交 → 收银台即停。

用法：
    # 无提交，只到订单页核对（演练/预演）
    .venv/bin/python scripts/rush.py --show-tag libenben_780_20261128 --expected-total 780.00

    # 开售等待 + 单次授权提交
    .venv/bin/python scripts/rush.py --wait-open 15:00 --submit \
        --show-tag renxianqi_488_20261206 --expected-total 488.00

    # 人工取消订单后闭环审计记录
    .venv/bin/python scripts/rush.py --clear-record --show-tag <tag>

流程与纪律见 docs/抢票模式.md 与 docs/原理与流程.md。付款永远人工。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dunpiao import engine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rush.py",
        description="抢票模式：开售倒计时 + 三击热路径（CTA→确定→立即提交），付款人工",
    )
    engine.add_common_args(ap)
    engine.add_rush_args(ap)
    ap.add_argument("--simulate", action="store_true",
                    help="模拟演练：CTA 处于预约/未开售态时仍点击（不提交）")
    args = ap.parse_args()
    return engine.run(args, mode="rush")


if __name__ == "__main__":
    raise SystemExit(main())
