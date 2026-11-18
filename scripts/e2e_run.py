# -*- coding: utf-8 -*-
"""E2E 单进程运行器（无提交版）——李大奔 BENZO ¥780 演出。

单进程从详情页待命自动推进到订单确认页并核对，**不点提交**。
运行中无人介入；任何未知状态/超时/字段不符即停机并留证。

用法：
    .venv/bin/python scripts/e2e_run.py --serial $(cat /tmp/.hat_serial) \
        [--expected-total 780.00] [--max-state-wait 15] [--submit]

--submit 默认关闭；开启即代表用户单次授权真实提交（最多一次，不盲重试）。
"""
import argparse
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


class Runner:
    def __init__(self, d, out: Path, expected_total: str, max_wait: float):
        self.d = d
        self.out = out
        self.expected = Decimal(expected_total)
        self.max_wait = max_wait
        self.out.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str) -> None:
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        with open(self.out / "run.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def snap(self, tag: str):
        xml = self.d.dump_hierarchy()
        (self.out / f"{tag}.xml").write_text(xml, encoding="utf-8")
        self.d.screenshot(str(self.out / f"{tag}.png"))
        root = ET.fromstring(xml)
        rep = probe.analyze(root, "cn.damai", self.d.app_current().get("activity", ""))
        cta = rep["cta"]
        if cta.get("container_present") and cta.get("container_bounds"):
            try:
                cta.update(probe.pixel_check_cta(self.d.screenshot(), cta["container_bounds"]) or {})
            except Exception as e:
                self.log(f"像素验证失败 {type(e).__name__}（不影响分类）")
        return root, rep

    def wait_state(self, pred, tag: str, attempts: int = 6, gap: float = 1.5):
        """有界等待：轮询直到 pred(rep) 为真或次数用尽。"""
        for i in range(attempts):
            root, rep = self.snap(f"{tag}_{i}")
            if pred(rep):
                return root, rep
            time.sleep(gap)
        return None, rep

    def tap(self, bounds, label: str) -> None:
        x1, y1, x2, y2 = bounds
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        self.log(f"点击 {label} ({x},{y})")
        self.d.shell(f"input tap {x} {y}")


def parse_bounds(s):
    return [int(x) for x in re.findall(r"\d+", s)] if s else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=None)
    ap.add_argument("--expected-total", default="780.00")
    ap.add_argument("--max-state-wait", type=float, default=15.0)
    ap.add_argument("--submit", action="store_true", help="单次授权真实提交（默认关闭）")
    args = ap.parse_args()

    import uiautomator2 as u2
    d = u2.connect(args.serial)
    out = ROOT / "logs" / f"e2e_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    r = Runner(d, out, args.expected_total, args.max_state_wait)
    r.log(f"=== E2E 运行开始（无提交版，expected_total={args.expected_total}）===")

    # ---- 0) 自恢复到详情页（BACK 有界回退，不点任何业务按钮）----
    root, rep = r.snap("s0_check")
    for i in range(4):
        if rep["state"] == "detail_page":
            break
        if rep["state"].startswith("sku") or rep["state"] == "order_confirm_page":
            r.log(f"s0: 当前 {rep['state']}，BACK 返回详情页")
            r.d.shell("input keyevent 4")
            time.sleep(2.0)
            root, rep = r.snap(f"s0_back_{i}")
        else:
            break
    if rep["state"] != "detail_page":
        r.log(f"STOP: 无法回到详情页（state={rep['state']}）——请手动打开目标演出详情页后重跑")
        return 1

    # ---- 1) 详情页待命 ----
    root, rep = r.wait_state(lambda p: p["state"] == "detail_page", "s0_detail")
    if root is None:
        r.log(f"STOP: 未在详情页（state={rep['state']}）——请手动打开目标演出详情页后重跑")
        return 1

    # ---- 1) 等待 CTA 亮橙 → 点击一次 → 进 SKU ----
    root, rep = r.wait_state(
        lambda p: p["cta"].get("likely_active") is True, "s1_waitcta"
    )
    if root is None:
        r.log(f"STOP: CTA 未呈亮橙可购态（appearance={rep['cta'].get('appearance_hint')}，"
              f"mean={rep['cta'].get('mean_rgb')}）——按钮不可购或状态未识别")
        return 1
    r.tap(rep["cta"]["container_bounds"], "详情页购票 CTA")
    root, rep = r.wait_state(lambda p: p["state"].startswith("sku"), "s1_after")
    if root is None:
        r.log(f"STOP: 点击 CTA 后未进 SKU 页（state={rep['state']}）")
        return 1
    r.log(f"s1: 进入 SKU 页")

    # ---- 2) 等待票档加载 → 选在售票档（候选必须唯一）----
    root, rep = r.wait_state(
        lambda p: bool(p.get("sku") and p["sku"]["tier_count"] > 0),
        "s2_loadtiers",
    )
    if root is None:
        r.log("STOP: 票档列表未在有界时间内加载（页面未就绪或结构变化）")
        return 1
    def tier_candidates(p_root):
        sold, tiers = set(), []
        for n in p_root.iter("node"):
            if (n.get("resource-id") or "").endswith("project_detail_perform_price_flowlayout"):
                for tier in n:
                    tb = parse_bounds(tier.get("bounds"))
                    tiers.append(tb)
                    if any((t.get("text") or "").strip() == "缺货登记" for t in tier.iter("node")):
                        sold.add(tuple(tb))
        return [b for b in tiers if tuple(b) not in sold]

    cands = tier_candidates(root)
    if len(cands) != 1:
        r.log(f"STOP: 在售票档候选 {len(cands)} ≠ 1（本运行器按保守规则不盲选）")
        return 1
    r.tap(cands[0], "在售票档")
    root, rep = r.wait_state(lambda p: p["state"] == "sku_page", "s2_selected")
    if root is None:
        r.log(f"STOP: 选档后状态异常（{rep['state']}）")
        return 1
    # 两步制：确认按钮亮橙才点
    root, rep = r.wait_state(lambda p: p["cta"].get("likely_active") is True, "s2_waitconfirm")
    if root is None:
        r.log(f"STOP: 确定按钮未亮橙（mean={rep['cta'].get('mean_rgb')}）")
        return 1
    r.tap(rep["cta"]["container_bounds"], "SKU 确定按钮")
    root, rep = r.wait_state(lambda p: p["state"] == "order_confirm_page", "s2_after")
    if root is None:
        r.log(f"STOP: 确定后未到订单页（state={rep['state']}）")
        return 1
    r.log("s2: 到达订单确认页")

    # ---- 3) 等订单字段渲染完成 → 全字段核对（不提交）----
    root, rep = r.wait_state(
        lambda p: bool((p.get("order") or {}).get("submit_button"))
        and bool((p.get("order") or {}).get("quantity_text"))
        and bool((p.get("order") or {}).get("total_price_text")),
        "s3_load",
        attempts=8,
        gap=1.0,
    )
    if root is None:
        r.log(f"STOP: 订单字段未在有界时间内就绪（order={rep.get('order')}）")
        return 1
    order = rep.get("order") or {}
    qty = order.get("quantity_text")
    total = order.get("total_price_text")
    m = re.fullmatch(r"¥\s*([\d,]+(?:\.\d{1,2})?)", total or "")
    amount = Decimal(m.group(1).replace(",", "")) if m else None
    cfg = json.loads(re.sub(r"//[^\n]*", "", (ROOT / "config.local.jsonc").read_text(encoding="utf-8")))
    users = [u.strip() for u in (cfg.get("users") or []) if isinstance(u, str) and u.strip()]
    page_names = [
        (n.get("text") or "").strip()
        for n in root.iter("node")
        if (n.get("text") or "").strip() in users
    ]
    checks = {
        "submit_button_visible": bool(order.get("submit_button")),
        "quantity": qty,
        "amount": str(amount) if amount is not None else None,
        "amount_match": amount == r.expected,
        "attendees_in_page": len(page_names),
        "attendees_match": bool(users) and all(page_names.count(u) == 1 for u in users),
    }
    ok = (
        checks["submit_button_visible"]
        and checks["quantity"] == "×1张"
        and checks["amount_match"]
        and checks["attendees_match"]
    )
    r.log("s3: 订单核对 " + json.dumps(checks, ensure_ascii=False))
    r.snap("s3_final")
    if ok:
        r.log("RESULT: ✅ 端到端（无提交）通过——已到订单页且全字段核对一致，停在提交前")
    else:
        r.log("RESULT: ❌ 到达订单页但核对未全通过——停机，交人工检查")
        return 1
    if args.submit:
        r.log("STOP: --submit 需单次授权流程，本运行器未实现自动提交（见 E2E-05）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
