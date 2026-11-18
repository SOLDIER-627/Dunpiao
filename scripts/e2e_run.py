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
from src.dunpiao import clock_sync  # noqa: E402

POLL_PAGE = 0.2   # 页面态轮询间隔（上游 wait_for_page_state 默认）
POLL_FAST = 0.05  # 就绪检查轮询间隔（上游 poll_until 默认）

# ---- buy_button_guard 文案护栏（照抄上游 buy_button_guard.py，含 issue 注记）----
# 只有可购文案才视为安全；预约/预售类文案一律拦截。本机 Canvas 自绘 CTA 无文案
# 节点时由像素闸门决定；一旦出现文案则必须过文案护栏。
SAFE_TEXTS = frozenset({
    "立即购买", "立即购票", "立即抢票", "立即预定", "立即预订",  # issue #29
    "Book Now",  # 国际化兑底（issue #29）
    "选座购买", "购买", "抢票", "预定",
})
BLOCKED_TEXTS = frozenset({
    "预约抢票", "预约", "预售", "即将开抢", "待开售", "未开售", "提交抢票预约",
})


def cta_text_guard(root, bounds):
    """决策点文案护栏：CTA 区域内出现 BLOCKED 文案则拒绝点击。

    返回 (allow, note)。无任何文案节点（本机 Canvas 自绘常态）→ 放行给像素闸门。
    """
    if not bounds:
        return True, "no_bounds"
    x1, y1, x2, y2 = bounds
    note = []
    for n in root.iter("node"):
        text = (n.get("text") or "").strip()
        if not text:
            continue
        nb = parse_bounds(n.get("bounds"))
        if not nb:
            continue
        # 与 CTA 容器区域相交才纳入护栏范围
        if nb[0] < x2 and nb[2] > x1 and nb[1] < y2 and nb[3] > y1:
            if text in BLOCKED_TEXTS:
                return False, f"blocked_text:{text}"
            if text in SAFE_TEXTS:
                note.append(f"safe_text:{text}")
    return True, ",".join(note) or "no_text"


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

    def fast_poll(self, fn, tag: str, timeout: float, poll: float = 0.05):
        """u2 快查询轮询（实测 ~50ms/轮，不 dump 不截图）。

        上游 rush_mode 同思路（单 ID 选择器 ~60ms/轮）；dump 只留给必须
        读文本/标签的关键点。返回 True/False。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if fn():
                    return True
            except Exception as e:
                self.log(f"{tag}: 快查询异常重试 {type(e).__name__}")
            time.sleep(poll)
        return False

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
    ap.add_argument(
        "--wait-open", metavar="HH:MM|YYYY-MM-DD HH:MM",
        help="开售等待模式：开售时刻前只在详情页待命，到点后才开始点击",
    )
    ap.add_argument(
        "--countdown-lead-ms", type=int, default=3000,
        help="开售前多少毫秒开始预轮询（上游 config.py countdown_lead_ms 默认 3000）",
    )
    ap.add_argument(
        "--ignore-clock-trust", action="store_true",
        help="时钟信任为 severe 时仍然继续（默认拒绝，上游语义为降级/拒绝）",
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
    for i in range(4):
        if rep["state"] == "detail_page":
            break
        if rep["state"].startswith("sku") or rep["state"] == "order_confirm_page":
            r.log(f"s0: 当前 {rep['state']}，BACK 返回详情页")
            d.shell("input keyevent 4")
            root, rep = r.wait_until(
                lambda rt, p: p["state"] == "detail_page",
                f"s0_back_{i}", timeout=3.0, poll_interval=POLL_PAGE,
            )
            # 超时不 break：下一轮继续 BACK（上游 _recover_to_navigation_start 阶梯）
        else:
            break
    if rep.get("state") != "detail_page":
        r.log(f"STOP: 不在详情页（state={rep.get('state')}）——请手动打开目标演出详情页后重跑")
        return 1

    # ---- 0.5) 开售等待模式（上游 wait_for_sale_start 骨架：clock_sync + lead 轮询）----
    if args.wait_open:
        raw = args.wait_open
        try:
            rough_wall = datetime.datetime.now().astimezone()
            if len(raw) > 5:
                naive = datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M")
            else:
                # strptime("%H:%M") 默认年份 1900（实测踩坑：目标落到过去、倒计时为负、提前点击）
                naive = datetime.datetime.combine(
                    rough_wall.date(), datetime.datetime.strptime(raw, "%H:%M").time()
                )
        except ValueError:
            r.log(f"STOP: 无法解析开售时刻 {raw!r}（支持 HH:MM 或 YYYY-MM-DD HH:MM）")
            return 1
        obs = clock_sync.sample_clock()
        # 实测踩坑：anchor 两采样点必须紧邻且在 sample_clock 之后——
        # sntp 耗时 1~3s，夹在中间会让 deadline 整体晚同样多（首次实测晚 1.77s）
        anchor_wall = datetime.datetime.now().astimezone()
        anchor_mono = time.monotonic()
        target = naive.replace(tzinfo=anchor_wall.tzinfo)
        if target <= anchor_wall:
            target += datetime.timedelta(days=1)  # 已过 → 明天
        dl = clock_sync.build_monotonic_sale_deadline(
            target, anchor_wall, anchor_mono, obs,
        )
        r.log(f"clock: trust={dl.trust_level}({dl.trust_reason}) "
              f"source={obs.source}/{obs.detail} 开售={target:%Y-%m-%d %H:%M:%S%z}")
        if dl.degrade_to_cta and not args.ignore_clock_trust:
            r.log("STOP: 时钟信任 severe（未同步/偏移过大）——默认拒绝；"
                  "确信无误可用 --ignore-clock-trust")
            return 1
        lead = args.countdown_lead_ms / 1000.0
        # a) lead 之前：详情页待命，零点击零 dump；0.05s 粒度避免 sleep 过冲累积漂移
        #    （上游 sale_waiter 同款 sleep(min(0.05, remaining))，实测 1s 粒度会漂 ~1.7s/百秒）
        while True:
            remaining = dl.remaining_seconds(time.monotonic())
            if remaining <= lead:
                break
            time.sleep(min(0.05, remaining - lead))
        r.log(f"wait-open: 进入 lead 窗口（{args.countdown_lead_ms}ms），prewarm 取基线快照")
        # b) lead 窗口：prewarm 快照（只读）——坐标/像素基线/文案护栏，供 T0 直点
        root, rep = r.snap("s1_prewarm", pixel=True)
        if not rep["cta"].get("container_present"):
            r.log("STOP: prewarm 时 CTA 容器不可见——页面结构异常，不盲等")
            return 1
        prewarm_ok = rep["cta"].get("likely_active") is True
        allow, note = cta_text_guard(root, rep["cta"]["container_bounds"])
        if not allow:
            prewarm_ok = False
            r.log(f"wait-open: prewarm 文案护栏拦截（{note}）——T0 后走验证路径")
        else:
            r.log(f"wait-open: prewarm 就绪（likely_active={prewarm_ok}，{note}）")
        # c) 到点：deadline 前 0.05s 粒度待命（上游同款 min(0.05, remaining)）
        while True:
            remaining = dl.remaining_seconds(time.monotonic())
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))
        r.log("wait-open: 到点，进入点击窗口")
        # c2) T0 直点前廉价闸门（上游 _scheduled_sale_click_gate 思路）：
        #     只验 activity 未变（~50ms），不做全量 dump（~0.4s 会吃掉 T0 窗口）
        if prewarm_ok and "ProjectDetailActivity" not in d.app_current().get("activity", ""):
            prewarm_ok = False
            r.log("wait-open: T0 前 activity 变化，放弃直点走验证路径")

    # ---- 1) CTA 点击：T0 直点（prewarm）优先，否则亮橙闸门 + 文案护栏 ----
    root = None
    entered_fast = False
    if args.wait_open and prewarm_ok:
        r.tap(rep["cta"]["container_bounds"], "详情页购票 CTA（prewarm T0 直点）")
        flow = d(resourceId="cn.damai:id/project_detail_perform_price_flowlayout")
        if r.fast_poll(lambda: flow.exists, "s1_after_t0", timeout=3.0):
            entered_fast = True
            r.log("s1: T0 直点进入 SKU 页（快查询确认）")
    if not entered_fast:
        root, rep = r.wait_until(
            lambda rt, p: p["cta"].get("likely_active") is True,
            "s1_waitcta",
            timeout=5.0 if not args.wait_open else 8.0,
            poll_interval=POLL_FAST, pixel=True,
        )
        if root is None:
            r.log(f"STOP: CTA 未呈亮橙可购态（appearance={rep['cta'].get('appearance_hint')}）")
            return 1
        allow, note = cta_text_guard(root, rep["cta"]["container_bounds"])
        if not allow:
            r.log(f"STOP: CTA 文案护栏拦截（{note}）——疑似预约/预售态，不点击")
            return 1
        if note and note != "no_text":
            r.log(f"s1: CTA 文案护栏通过（{note}）")
        r.tap(rep["cta"]["container_bounds"], "详情页购票 CTA")
        # 快路径：票价容器出现即 SKU 页（u2 查询 ~50ms/轮 vs dump 轮 ~300ms/轮）
        flow = d(resourceId="cn.damai:id/project_detail_perform_price_flowlayout")
        if not r.fast_poll(lambda: flow.exists, "s1_skupoll", timeout=2.5):
            r.log("STOP: 点击 CTA 后票价容器未出现（未进 SKU 或页面结构变化）")
            return 1
        root = None  # 状态由 s2_tiers 的 dump 统一验证
    r.log("s1: 进入 SKU 页（快查询确认）")

    # ---- 2) 票档标签计数稳定（快路径）→ 单次 dump 拿 bounds 与护栏 ----
    # 实测根因：『缺货登记』标签晚于票档框渲染；u2 文本计数 ~48ms/轮，
    # 计数在 ≥0.8s 窗口内不变且 SKU 驻留 ≥1.2s 才认定标签已定，然后 dump 一次。
    last_tag, changed_at = None, time.monotonic()
    sku_entered_at = time.monotonic()
    settled = False
    while time.monotonic() < sku_entered_at + 5.0:
        c = d(text="缺货登记").count
        now = time.monotonic()
        if c != last_tag:
            last_tag, changed_at = c, now
        elif now - changed_at >= 0.8 and now - sku_entered_at >= 1.2:
            settled = True
            break
        time.sleep(0.05)
    root, rep = r.snap("s2_tiers")
    if not rep["state"].startswith("sku"):
        r.log(f"STOP: 标签稳定时状态异常（state={rep['state']}）")
        return 1
    if not settled:
        r.log(f"STOP: 票档标签计数未稳定（5s 内 last={last_tag}）")
        return 1
    all_tiers, cands = tier_candidates(root)
    if len(cands) != 1:
        r.log(f"STOP: 在售票档候选 {len(cands)}/{len(all_tiers)} ≠ 1（保守规则不盲选）")
        return 1
    r.log(f"s2: 票档共 {len(all_tiers)}，缺货标记 {last_tag}，在售候选 1（标签稳定）")
    r.tap(cands[0], "在售票档")
    # 快路径：确定按钮亮橙用仅截图像素轮询（~146ms/轮），bounds 来自刚拿的 dump
    confirm_bounds = rep["cta"]["container_bounds"]
    def _confirm_bright():
        res = probe.pixel_check_cta(d.screenshot(), confirm_bounds) or {}
        return res.get("likely_active") is True
    if not r.fast_poll(_confirm_bright, "s2_confirmpix", timeout=3.0):
        r.log("STOP: 确定按钮未亮橙（仅截图轮询超时）")
        return 1
    allow, note = cta_text_guard(root, confirm_bounds)
    if not allow:
        r.log(f"STOP: 确定按钮文案护栏拦截（{note}）")
        return 1
    r.tap(confirm_bounds, "SKU 确定按钮")
    # 快路径：订单页标记（上游 _wait_for_submit_ready 同款 checkbox ID）
    chk = d(resourceId="cn.damai:id/checkbox")
    if not r.fast_poll(lambda: chk.exists, "s2_orderpoll", timeout=3.0):
        r.log("STOP: 确定后订单页标记未出现（未跳转或页面结构变化）")
        return 1
    root, rep = r.snap("s2_after")
    if rep["state"] != "order_confirm_page":
        r.log(f"STOP: 确定后状态异常（state={rep['state']}）")
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
    if not ok:
        r.snap("s3_final")
        r.log("RESULT: ❌ 到达订单页但核对未全通过——停机，交人工检查")
        return 1
    if not args.submit:
        r.snap("s3_final")
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
