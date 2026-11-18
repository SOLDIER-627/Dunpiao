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
from src.dunpiao import maoyan as MY  # noqa: E402
from src.dunpiao import maoyan_flow  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rush.py",
        description="抢票模式：开售倒计时 + 三击热路径（CTA→确定→立即提交），付款人工",
    )
    engine.add_common_args(ap)
    engine.add_rush_args(ap)
    ap.add_argument(
        "--platform", choices=("auto", "damai", "maoyan"), default="auto",
        help="平台（auto=按前台包名判断）：大麦走 engine，猫眼走 maoyan_flow",
    )
    ap.add_argument("--price", default=None,
                    help="猫眼：目标票价数字（如 288），优先于 config 的 price_index")
    ap.add_argument("--simulate", action="store_true",
                    help="猫眼模拟演练：CTA 处于预约/未开售态时仍点击（不提交）")
    args = ap.parse_args()

    plat = args.platform
    if plat == "auto":
        import uiautomator2 as u2
        cur = (u2.connect(args.serial) if args.serial else u2.connect()).app_current()
        plat = "maoyan" if cur.get("package") == MY.PACKAGE else "damai"
        print(f"[平台] 前台包名 {cur.get('package')} → {plat}")

    if plat == "maoyan":
        args.click = True            # 猫眼链路默认点 CTA/票档/确认（与大麦一致）
        args.allow_blocked_cta = args.simulate
        return maoyan_flow.run(args)
    return engine.run(args, mode="rush")


if __name__ == "__main__":
    raise SystemExit(main())
