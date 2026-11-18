#!/usr/bin/env python
"""回流模式（蹲守）——进 SKU 面板 → 周期监听目标票档 → 缺货登记消失即接管执行链。

用法：
    # 蹲守（不提交，只到订单页核对）
    .venv/bin/python scripts/reflow.py --show-tag forever_488_20261121 \
        --expected-total 488.00 --session-index 1 --expect-session-date 2026.11.21

    # 蹲守 + 单次授权提交（触发后自动走三击流程到收银台，付款人工）
    .venv/bin/python scripts/reflow.py --submit --show-tag forever_488_20261121 \
        --expected-total 488.00 --session-index 1 --expect-session-date 2026.11.21 \
        --reflow-interval 2 --reflow-refresh 15 --reflow-max-minutes 300

    # 人工处理完订单后闭环审计记录
    .venv/bin/python scripts/reflow.py --clear-record --show-tag <tag>

要点（实测）：
  - 大麦 SKU 面板库存不自动刷新，必须周期性 BACK→CTA→重选场次（--reflow-refresh）
  - 两级面板（场次→票档）场次项自绘无文本，只能按 --session-index 点；
    最终防线是 --expect-session-date（订单页场次文本核对）
  - 回流场景面板底部是 ¥0（未选档），预选自动关闭，必须显式点票价

流程与纪律见 docs/回流模式.md 与 docs/原理与流程.md。付款永远人工。
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
        prog="reflow.py",
        description="回流模式：周期监听目标票档缺货登记消失，触发后走同一套执行链",
    )
    engine.add_common_args(ap)
    engine.add_reflow_args(ap)
    args = ap.parse_args()
    return engine.run(args, mode="reflow")


if __name__ == "__main__":
    raise SystemExit(main())
