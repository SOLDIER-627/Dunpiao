# -*- coding: utf-8 -*-
"""PH-05 受控步进流程（2026-11-18 单次授权运行）。

原则：
- 每步执行前重新 dump 并核验状态，状态不符即中止
- 每步至多一次点击，坐标来自当次 dump 的 bounds
- 全程留证：截图 + XML + 日志
- 终点：订单提交后即停，付款环节完全交人工
- 触发滑块/异常验证 = 立即中止交人工（红线）
"""
import datetime
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dunpiao import probe  # noqa: E402
from src.dunpiao.selectors import SUBMIT_TEXTS  # noqa: E402

SERIAL = (ROOT / ".." / ".." / "tmp" / ".hat_serial")
LOG = ROOT / "logs"
TS = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
STEP_DIR = LOG / f"ph05_{TS}"
STEP_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(STEP_DIR / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def snapshot(d, tag: str):
    xml = d.dump_hierarchy()
    (STEP_DIR / f"{tag}.xml").write_text(xml, encoding="utf-8")
    d.screenshot(str(STEP_DIR / f"{tag}.png"))
    root = ET.fromstring(xml)
    report = probe.analyze(root, "cn.damai", d.app_current().get("activity", ""))
    cta = report["cta"]
    if cta.get("container_present") and cta.get("container_bounds"):
        try:
            report["cta"].update(probe.pixel_check_cta(d.screenshot(), cta["container_bounds"]) or {})
        except Exception as e:
            log(f"snapshot: 像素验证失败 {type(e).__name__}")
    return root, report


def parse_bounds(s):
    return [int(x) for x in re.findall(r"\d+", s)] if s else None


def center(b):
    x1, y1, x2, y2 = b
    return (x1 + x2) // 2, (y1 + y2) // 2


def step1_to_sku(d) -> int:
    """详情页 → 点击购票 CTA（像素验证通过后坐标点击一次）→ 应到 SKU 页。"""
    root, rep = snapshot(d, "s1_detail")
    if rep["state"] != "detail_page":
        log(f"ABORT s1: 状态非 detail_page（{rep['state']}）")
        return 1
    cta = rep["cta"]
    if not cta.get("container_bounds"):
        log("ABORT s1: CTA 容器无 bounds")
        return 1
    if not cta.get("button_visually_rendered") or not cta.get("likely_active"):
        log(f"ABORT s1: CTA 未呈已验证的亮橙态（mean={cta.get('mean_rgb')}，appearance={cta.get('appearance_hint')}），不点击")
        return 1
    x, y = center(cta["container_bounds"])
    log(f"s1: CTA 像素验证通过（mean={cta['mean_rgb']}），坐标点击 ({x},{y})")
    d.shell(f"input tap {x} {y}")  # HyperOS 安全设置开启后 shell 层注入可用；u2 UiAutomation 注入在 Android 16 被拒
    time.sleep(2.5)
    root, rep = snapshot(d, "s1_after")
    log(f"s1: 点击后状态 = {rep['state']}")
    return 0 if rep["state"].startswith("sku") else 1


def step2_pick_tier(d) -> int:
    """SKU 页 → 选票档 → 核对确认按钮亮橙 → 点确定 → 订单确认页。"""
    root, rep = snapshot(d, "s2_sku")
    if not rep["state"].startswith("sku"):
        log(f"ABORT s2: 状态非 sku_page（{rep['state']}）")
        return 1
    sku = rep["sku"]
    if not sku["tier_bounds"]:
        log("ABORT s2: 未找到票档条目")
        return 1
    # 找出带"缺货登记"标签的档，排除之；无标签者 = 在售候选
    sold_bounds = set()
    for n in root.iter("node"):
        if (n.get("resource-id") or "").endswith("project_detail_perform_price_flowlayout"):
            for tier in n:
                tb = parse_bounds(tier.get("bounds"))
                if any(
                    (t.get("text") or "").strip() in ("缺货登记",)
                    for t in tier.iter("node")
                ):
                    sold_bounds.add(tuple(tb))
    candidates = [b for b in (parse_bounds(x) for x in sku["tier_bounds"]) if tuple(b) not in sold_bounds]
    log(f"s2: 共 {len(sku['tier_bounds'])} 档，{len(sold_bounds)} 档缺货，在售候选 {len(candidates)} 档")
    if len(candidates) != 1:
        log(f"ABORT s2: 在售候选数 {len(candidates)} ≠ 1，不盲目点击")
        return 1
    x, y = center(candidates[0])
    log(f"s2: 点击在售票档中心 ({x},{y}) bounds={candidates[0]}")
    d.shell(f"input tap {x} {y}")  # HyperOS 安全设置开启后 shell 层注入可用；u2 UiAutomation 注入在 Android 16 被拒
    time.sleep(2.5)
    root, rep = snapshot(d, "s2_after")
    log(f"s2: 点击后状态 = {rep['state']}")
    if rep["state"] != "sku_page":
        log("ABORT s2: 选票档后未停在 SKU 页，不继续点击")
        return 1
    cta = rep["cta"]
    if not cta.get("container_bounds") or not cta.get("likely_active"):
        log(f"ABORT s2: 确定按钮未呈已验证的亮橙态（mean={cta.get('mean_rgb')}），不点击")
        return 1
    x, y = center(cta["container_bounds"])
    log("s2: 确定按钮视觉核验通过，点击一次并等待订单页")
    d.shell(f"input tap {x} {y}")
    time.sleep(2.5)
    root, rep = snapshot(d, "s2_after_confirm")
    log(f"s2: 确定后状态 = {rep['state']}")
    return 0 if rep["state"] == "order_confirm_page" else 1


def step3_verify_and_submit(d) -> int:
    """订单确认页 → 机读核对清单 → 单次授权点击『立即提交』→ 停止。"""
    root, rep = snapshot(d, "s3_order")
    if rep["state"] != "order_confirm_page":
        log(f"ABORT s3: 状态非 order_confirm_page（{rep['state']}）")
        return 1
    order = rep.get("order") or {}
    if not order.get("submit_button"):
        log("ABORT s3: 提交按钮不可见")
        return 1
    qty = order.get("quantity_text")
    total = order.get("total_price_text")
    if qty != "×1张":
        log(f"ABORT s3: 张数异常（{qty!r} ≠ ×1张）")
        return 1
    amount_match = re.fullmatch(r"¥\s*([\d,]+(?:\.\d{1,2})?)", total or "")
    amount = Decimal(amount_match.group(1).replace(",", "")) if amount_match else None
    if amount != Decimal("780.00"):
        log(f"ABORT s3: 总价异常（{total!r}，预期精确金额 ¥780.00）")
        return 1
    # 观演人姓名 vs 配置（不打印姓名本身）
    import json as _json
    cfg = _json.loads(re.sub(r"//[^\n]*", "", (ROOT / "config.local.jsonc").read_text(encoding="utf-8")))
    users = [u.strip() for u in (cfg.get("users") or []) if isinstance(u, str) and u.strip()]
    page_names = [
        (n.get("text") or "").strip()
        for n in root.iter("node")
        if (n.get("text") or "").strip() in users
    ]
    if not users or any(page_names.count(u) != 1 for u in users):
        log("ABORT s3: 页面观演人与配置未逐一匹配——核对失败")
        return 1
    log(f"s3: 核对通过——观演人匹配配置 {len(page_names)} 条、{qty}、{total}、提交按钮可见")
    log("s3: 【单次授权】点击『立即提交』，此后流程终止，付款交人工")
    x, y = center(order["submit_button"]["bounds"])
    d.shell(f"input tap {x} {y}")  # HyperOS 安全设置开启后 shell 层注入可用；u2 UiAutomation 注入在 Android 16 被拒
    time.sleep(3.0)
    root, rep = snapshot(d, "s3_after_submit")
    activity = d.app_current().get("activity", "").split(".")[-1]
    log(f"s3: 提交后状态 = {rep['state']}，activity={activity}")
    log("s3: 流程终止——不触碰任何后续页面，付款环节交人工")
    return 0


STEPS = {"s1": step1_to_sku, "s2": step2_pick_tier, "s3": step3_verify_and_submit}


def main() -> int:
    import uiautomator2 as u2

    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step not in STEPS:
        print("usage: ph05_flow.py {s1|s2|s3}")
        return 2
    serial = None
    env = sys.argv[2] if len(sys.argv) > 2 else None
    d = u2.connect(serial)
    log(f"=== step {step} begin（授权运行 {TS}）===")
    rc = STEPS[step](d)
    log(f"=== step {step} end rc={rc} ===")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
