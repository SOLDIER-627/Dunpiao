# -*- coding: utf-8 -*-
"""E2E 单进程运行器——详情页待命 → SKU → 订单核对 →（可选单次提交）→ 收银台即停。

等待策略照上游 HaTickets orchestrator 的实现，不自造 sleep：
- 页面态轮询：deadline + poll_interval=0.2（orchestrator.py:1042 wait_for_page_state）
- 就绪/热路径轮询：poll_interval=0.05（fast_pipeline.py:61 poll_until 默认值）
- u2 内部等待关闭：settings["wait_timeout"]=0, operation_delay=(0,0)（orchestrator.py:922）
- 点击后立即进入轮询，无固定 post-click sleep
- 像素验证只在决策点做（CTA/确定按钮），中间态只 dump 不截图

用法：
    .venv/bin/python scripts/e2e_run.py                # 无提交，到订单页核对即停
    .venv/bin/python scripts/e2e_run.py --submit       # 单次提交到收银台（先记录后点击）
    .venv/bin/python scripts/e2e_run.py --clear-record # 人工取消订单后闭环闸门记录
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

POLL_PAGE = 0.2   # 页面态轮询间隔（上游 wait_for_page_state 默认）
POLL_FAST = 0.05  # 就绪检查轮询间隔（上游 poll_until 默认）


def parse_bounds(s):
    return [int(x) for x in re.findall(r"\d+", s)] if s else None


class Runner:
    def __init__(self, d, out: Path, expected_total: str):
        self.d = d
        self.out = out
        self.expected = Decimal(expected_total)
        self.out.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str) -> None:
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        with open(self.out / "run.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def snap(self, tag: str, pixel: bool = False):
        """一次 dump 分析；像素验证只在决策点（pixel=True）做。"""
        xml = self.d.dump_hierarchy()
        (self.out / f"{tag}.xml").write_text(xml, encoding="utf-8")
        root = ET.fromstring(xml)
        rep = probe.analyze(root, "cn.damai", self.d.app_current().get("activity", ""))
        cta = rep["cta"]
        if pixel and cta.get("container_present") and cta.get("container_bounds"):
            img = self.d.screenshot()
            img.save(str(self.out / f"{tag}.png"))
            try:
                cta.update(probe.pixel_check_cta(img, cta["container_bounds"]) or {})
            except Exception:
                self.log("像素验证失败（不影响分类）")
        return root, rep

    def wait_until(self, pred, tag: str, timeout: float, poll_interval: float,
                   pixel: bool = False):
        """上游 wait_for_page_state 模式：deadline 轮询，先查后睡，无固定 sleep。"""
        deadline = time.monotonic() + timeout
        last = (None, None)
        i = 0
        while time.monotonic() < deadline:
            last = self.snap(f"{tag}_{i}", pixel=pixel)
            if pred(*last):
                return last
            time.sleep(poll_interval)
            i += 1
        return None, last[1]

    def tap(self, bounds, label: str) -> None:
        x1, y1, x2, y2 = bounds
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        self.log(f"点击 {label} ({x},{y})")
        self.d.shell(f"input tap {x} {y}")


def tier_candidates(root):
    """在售票档 = 容器内无『缺货登记』标签的档（XML 层判别，实测结论）。
    返回 (全部档, 在售档)。标签后于 bounds 渲染，调用方必须等签名稳定。"""
    sold, tiers = set(), []
    for n in root.iter("node"):
        if (n.get("resource-id") or "").endswith(
            "project_detail_perform_price_flowlayout"
        ):
            for tier in n:
                tb = parse_bounds(tier.get("bounds"))
                tiers.append(tb)
                if any(
                    (t.get("text") or "").strip() == "缺货登记" for t in tier.iter("node")
                ):
                    sold.add(tuple(tb))
    all_tiers = [b for b in tiers if b]
    return all_tiers, [b for b in all_tiers if tuple(b) not in sold]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=None)
    ap.add_argument("--expected-total", default="780.00")
    ap.add_argument("--submit", action="store_true", help="单次授权真实提交（默认关闭）")
    ap.add_argument("--show-tag", default="libenben_780_20261128", help="提交闸门记录的演出标识")
    ap.add_argument(
        "--force-override-once", action="store_true",
        help="同演出已有活跃提交记录时覆盖一次（需人工确认历史订单已取消/未付款）",
    )
    ap.add_argument(
        "--clear-record", action="store_true",
        help="人工已取消/处理完订单后闭环记录（标记 cancelled_by_user，闸门重新放行）",
    )
    args = ap.parse_args()

    out = ROOT / "logs" / f"e2e_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # ---- 记录闭环：人工取消/处理完后，把闸门记录标记为已处理 ----
    if args.clear_record:
        gate = ROOT / "logs" / "submit_record.json"
        recs = json.loads(gate.read_text(encoding="utf-8")) if gate.exists() else []
        n = 0
        for x in recs:
            if x.get("show_tag") == args.show_tag and x.get("status") != "cancelled_by_user":
                x["status"] = "cancelled_by_user"
                x["resolved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                n += 1
        gate.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已把 {args.show_tag} 的 {n} 条提交记录标记为 cancelled_by_user，闸门重新放行")
        return 0

    import uiautomator2 as u2
    d = u2.connect(args.serial)
    # 上游 orchestrator.py:922 —— 关闭 u2 内部等待，避免隐式阻塞
    d.settings["wait_timeout"] = 0
    d.settings["operation_delay"] = (0, 0)
    r = Runner(d, out, args.expected_total)
    r.log(f"=== E2E 运行开始（submit={'ON' if args.submit else 'OFF'}，"
          f"expected_total={args.expected_total}）===")

    # ---- 0) 自恢复到详情页（BACK 后 deadline 轮询，不点任何业务按钮）----
    root, rep = r.snap("s0_check")
    for i in range(3):
        if rep["state"] == "detail_page":
            break
        if rep["state"].startswith("sku") or rep["state"] == "order_confirm_page":
            r.log(f"s0: 当前 {rep['state']}，BACK 返回详情页")
            d.shell("input keyevent 4")
            root, rep = r.wait_until(
                lambda rt, p: p["state"] == "detail_page",
                f"s0_back_{i}", timeout=3.0, poll_interval=POLL_PAGE,
            ) or (None, rep)
            if root is None:
                break
        else:
            break
    if rep.get("state") != "detail_page":
        r.log(f"STOP: 不在详情页（state={rep.get('state')}）——请手动打开目标演出详情页后重跑")
        return 1

    # ---- 1) CTA 亮橙闸门（决策点，像素验证）→ 点击 → 立即轮询 SKU ----
    root, rep = r.wait_until(
        lambda rt, p: p["cta"].get("likely_active") is True,
        "s1_waitcta", timeout=5.0, poll_interval=POLL_PAGE, pixel=True,
    )
    if root is None:
        r.log(f"STOP: CTA 未呈亮橙可购态（appearance={rep['cta'].get('appearance_hint')}）")
        return 1
    r.tap(rep["cta"]["container_bounds"], "详情页购票 CTA")
    root, rep = r.wait_until(
        lambda rt, p: p["state"].startswith("sku"),
        "s1_after", timeout=2.0, poll_interval=POLL_FAST,
    )
    if root is None:
        r.log(f"STOP: 点击 CTA 后未进 SKU 页（state={rep['state']}）")
        return 1
    r.log("s1: 进入 SKU 页")

    # ---- 2) 等票档渲染且签名稳定（标签后于 bounds 渲染，连续 3 轮不变才判定）----
    sig_state = {"last": None, "hits": 0, "i": 0}

    def _tiers_stable(rt, p):
        all_t, avail = tier_candidates(rt)
        sig = (len(all_t), tuple(tuple(b) for b in avail))
        if sig == sig_state["last"]:
            sig_state["hits"] += 1
        else:
            sig_state["last"], sig_state["hits"] = sig, 1
        sig_state["i"] += 1
        return sig_state["hits"] >= 3 and sig_state["i"] >= 3 and bool(avail)

    root, rep = r.wait_until(
        _tiers_stable, "s2_loadtiers", timeout=4.0, poll_interval=POLL_FAST,
    )
    if root is None:
        r.log("STOP: 票档列表未在有界时间内稳定加载")
        return 1
    all_tiers, cands = tier_candidates(root)
    if len(cands) != 1:
        r.log(f"STOP: 在售票档候选 {len(cands)}/{len(all_tiers)} ≠ 1（保守规则不盲选）")
        return 1
    r.log(f"s2: 票档共 {len(all_tiers)}，在售候选 1（签名稳定 {sig_state['hits']} 轮）")
    r.tap(cands[0], "在售票档")
    root, rep = r.wait_until(
        lambda rt, p: p["state"] == "sku_page", "s2_selected",
        timeout=1.5, poll_interval=POLL_FAST,
    )
    if root is None:
        r.log(f"STOP: 选档后状态异常（{rep['state']}）")
        return 1
    # 两步制：确定按钮亮橙才点（决策点，像素验证）
    root, rep = r.wait_until(
        lambda rt, p: p["cta"].get("likely_active") is True,
        "s2_waitconfirm", timeout=3.0, poll_interval=POLL_FAST, pixel=True,
    )
    if root is None:
        r.log(f"STOP: 确定按钮未亮橙（mean={rep['cta'].get('mean_rgb')}）")
        return 1
    r.tap(rep["cta"]["container_bounds"], "SKU 确定按钮")
    root, rep = r.wait_until(
        lambda rt, p: p["state"] == "order_confirm_page", "s2_after",
        timeout=2.5, poll_interval=POLL_FAST,
    )
    if root is None:
        r.log(f"STOP: 确定后未到订单页（state={rep['state']}）")
        return 1
    r.log("s2: 到达订单确认页")

    # ---- 3) 等订单字段渲染 → 全字段核对（不提交时到此为止）----
    root, rep = r.wait_until(
        lambda rt, p: bool((p.get("order") or {}).get("submit_button"))
        and bool((p.get("order") or {}).get("quantity_text"))
        and bool((p.get("order") or {}).get("total_price_text")),
        "s3_load", timeout=3.0, poll_interval=POLL_FAST,
    )
    if root is None:
        r.log(f"STOP: 订单字段未在有界时间内就绪（order={rep.get('order')}）")
        return 1
    order = rep["order"]
    m = re.fullmatch(r"¥\s*([\d,]+(?:\.\d{1,2})?)", order.get("total_price_text") or "")
    amount = Decimal(m.group(1).replace(",", "")) if m else None
    cfg = json.loads(re.sub(r"//[^\n]*", "", (ROOT / "config.local.jsonc").read_text("utf-8")))
    users = [u.strip() for u in (cfg.get("users") or []) if isinstance(u, str) and u.strip()]
    page_names = [
        (n.get("text") or "").strip()
        for n in root.iter("node") if (n.get("text") or "").strip() in users
    ]
    checks = {
        "submit_button_visible": bool(order.get("submit_button")),
        "quantity": order.get("quantity_text"),
        "amount": str(amount) if amount is not None else None,
        "amount_match": amount == r.expected,
        "attendees_in_page": len(page_names),
        "attendees_match": bool(users) and all(page_names.count(u) == 1 for u in users),
    }
    ok = all((checks["submit_button_visible"], checks["quantity"] == "×1张",
              checks["amount_match"], checks["attendees_match"]))
    r.log("s3: 订单核对 " + json.dumps(checks, ensure_ascii=False))
    r.snap("s3_final")
    if not ok:
        r.log("RESULT: ❌ 到达订单页但核对未全通过——停机，交人工检查")
        return 1
    if not args.submit:
        r.log("RESULT: ✅ 端到端（无提交）通过——已到订单页且全字段核对一致，停在提交前")
        return 0

    # ---- 4) 单次提交闸门：先记录后点击，活跃记录拦截 ----
    gate = ROOT / "logs" / "submit_record.json"
    records = json.loads(gate.read_text(encoding="utf-8")) if gate.exists() else []
    active = [
        x for x in records
        if x.get("show_tag") == args.show_tag
        and x.get("status") in ("submitted_intent", "awaiting_user_payment")
    ]
    if active and not args.force_override_once:
        r.log(f"STOP: 演出 {args.show_tag} 有一笔活跃待处理提交（{active[-1]['time']}，"
              f"status={active[-1].get('status')}）；订单已取消/处理完先跑 --clear-record，"
              "或本次覆盖用 --force-override-once")
        return 1
    records.append({
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "show_tag": args.show_tag,
        "status": "submitted_intent",
        "amount": str(amount),
        "evidence": out.name,
    })
    gate.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    r.log("s4: 【单次授权】点击『立即提交』——此后不盲重试，到收银台即停")
    r.tap(order["submit_button"]["bounds"], "立即提交")

    # ---- 5) 收银台即停（上游同款思路：轻量轮询 activity，命中才 dump 取证）----
    deadline = time.monotonic() + 8.0
    act = ""
    while time.monotonic() < deadline:
        act = d.app_current().get("activity", "")
        if "MspContainerActivity" in act:
            root5, rep5 = r.snap("s5_cashier")
            texts = {
                (n.get("text") or "").strip()
                for n in root5.iter("node")
            }
            if any("滑块" in t or "安全验证" in t for t in texts):
                r.log("STOP: 收银台出现验证拦截——红线，交人工")
                return 1
            records[-1]["status"] = "awaiting_user_payment"
            gate.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
            r.log(f"RESULT: ✅ 提交成功到达收银台——待用户支付，流程终止")
            return 0
        time.sleep(POLL_PAGE)
    r.log(f"STOP: 提交后未检测到收银台（activity={act.split('.')[-1]}）——不盲重试，交人工")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
