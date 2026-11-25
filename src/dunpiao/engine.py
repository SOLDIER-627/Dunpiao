# -*- coding: utf-8 -*-
"""两模式共用执行引擎（抢票 / 回流）。

流程骨架 = 上游 HaTickets fast_pipeline 四阶段：
  Phase 1 详情页   单次 dump → CTA 容器坐标 → 文案护栏（同一 dump 零成本）→ shell 点击
  Phase 2 入口等待 上游 _wait_for_purchase_entry：0.45s@0.03 快查询；超时回退双击
  Phase 3 SKU 页   单次 dump → 票价卡中心（price_index / ¥价格文本匹配）+ btn_buy_view
  Phase 4 shell 连点 上游 _shell_price_and_buy_until_confirm：≤0.9s 循环 + 确认页判定
  Phase 5 订单页   观演人 checkbox 补选 → 全字段核对（金额/张数/场次/观演人）
                   →（--submit）审计记录 → 提交 → 只读结果验证 → 收银台即停

两种模式的区别只在**触发阶段**：
  抢票（rush）  ：--wait-open 走 clock_sync 倒计时 + prewarm，T0 直点 CTA；
                  默认 --preselect 开启（预约预选已带入面板，首批只点确定）
  回流（reflow）：进入 SKU 面板后交给 reflow.watch 周期监听目标票档，
                  缺货登记消失即接管同一套执行链；面板未选档，预选自动关闭

安全纪律（与上游一致）：
  - 提交一次：selector 回退只在首次成功点击前；提交后只读 fail-closed
  - 提交前筛查四类阻塞弹窗（consent/待支付/验证码/瞬时错误）
  - 订单全字段核对不过就不提交；审计记录 submit_record.json 只记录不拦截
"""

from __future__ import annotations

import argparse
import atexit
import datetime
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

# 本文件在 src/dunpiao/ 下，项目根 = 上溯三层
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.dunpiao import probe  # noqa: E402
from src.dunpiao import recovery  # noqa: E402
from src.dunpiao import clock_sync  # noqa: E402
from src.dunpiao import coords_cache  # noqa: E402
from src.dunpiao import reflow  # noqa: E402
from src.dunpiao import runtime_lock  # noqa: E402
from src.dunpiao import maoyan as MY  # noqa: E402
from src.dunpiao.selectors import CTA_CONTAINER_ID  # noqa: E402

POLL_PAGE = 0.2   # 页面态轮询间隔（上游 wait_for_page_state 默认）
POLL_FAST = 0.05  # 就绪检查轮询间隔（上游 poll_until 默认）


def _maoyan_order_step(d, r, root_m, info, args) -> int:
    """猫眼订单页：核对金额/票档/数量 →（--submit）点「立即支付」。"""
    r.mark("order_confirm")
    line = info.get("tier_line") or {}
    amount = info.get("amount")
    r.log(f"s3: 猫眼订单页 金额={amount!r} 票档={line.get('name')!r} "
          f"单价={line.get('price')!r} 数量={line.get('qty')}")
    def _norm_amt(v):
        try:
            return round(float(str(v).replace(",", "")), 2)
        except (TypeError, ValueError):
            return None

    if args.expected_total and amount and _norm_amt(amount) != _norm_amt(args.expected_total):
        r.log(f"STOP: 猫眼金额不符（页面 {amount} != 期望 {args.expected_total}）——不提交")
        return 1
    sub = info.get("submit")
    if sub is None:
        r.log("STOP: 猫眼订单页未找到「立即支付」")
        return 1
    r.log(f"s3: 提交按钮 {sub['hit']!r} @{sub['center']}")
    r.mark("verified")
    if not args.submit:
        r.log("RESULT: ✅ 猫眼到订单页且核对通过（未提交；加 --submit 才点立即支付）")
        return 0
    r.tap(sub["bounds"], sub["hit"])
    r.mark("submit_tap")
    time.sleep(2.0)
    root_after, _ = r.snap("s6_maoyan")
    after = MY.page_info(root_after)
    r.log(f"s4: 提交后 activity={fast_app_current(d).get('activity')} "
          f"（只读，不再点击）")
    return 0


_FOCUS_RE = re.compile(r"mCurrentFocus=Window\{[^ ]+ [^ ]+ (?P<pkg>[^\s/]+)/(?P<act>[^\s}]+)")


# 开售前 prewarm 保护（上游 sale_waiter：_PREWARM_MIN_SLACK_MS=1200 /
# _PREWARM_WARN_DURATION_MS=500）
PREWARM_MIN_SLACK_MS = 1200
PREWARM_WARN_DURATION_MS = 500


def prewarm_probe(d) -> dict:
    """开售前只读快照——**只用定向选择器查询，绝不 dump_hierarchy**。

    上游 _capture_presale_readiness 同构：一次廉价查询换 CTA 坐标，
    不做整树 dump。原因（2026-11-23 11:00 胡彦斌场实测）：dump_hierarchy
    会等 UI 空闲，开售瞬间页面从预约态翻到开售态（重绘+动画+系统浮窗），
    单次 dump 阻塞 22.8s，出点后 20s 才点 CTA，票已售罄。
    """
    info = {"ready": False, "cta_bounds": None, "source": "selector",
            "activity": None, "blocked_text": None}
    try:
        act = fast_app_current(d)
        info["activity"] = act.get("activity")
        if "ProjectDetailActivity" not in (act.get("activity") or ""):
            info["source"] = "activity_mismatch"
            return info
    except Exception:
        info["source"] = "activity_error"
        return info
    # 单次 .info 同时拿 bounds + text + contentDescription（实测 .info 126ms，
    # 拆成 exists+两次 .info 是 3 个 roundtrip ≈ 370ms）
    try:
        node = d(resourceId=CTA_CONTAINER_ID).info
    except Exception:
        info["source"] = "container_missing"
        return info
    b = (node or {}).get("bounds") or {}
    bounds = [b.get("left"), b.get("top"), b.get("right"), b.get("bottom")]
    if None in bounds:
        info["source"] = "bounds_missing"
        return info
    info["cta_bounds"] = bounds
    # 文案护栏（无文本 = Canvas/Bricks 自绘，按上游 canvas 路径放行）
    txt = ((node.get("text") or "") + " " + (node.get("contentDescription") or "")).strip()
    if txt:
        blocked = next((w for w in ("已售罄", "缺货登记", "即将开抢", "已结束") if w in txt), None)
        if blocked:
            info["blocked_text"] = blocked
            info["source"] = "text_blocked"
            return info
    info["ready"] = True
    info["source"] = "text" if txt else "canvas(no_text)"
    return info


def fast_app_current(d) -> dict:
    """前台 activity 快查（~90ms）。

    uiautomator2 的 app_current() 走 `dumpsys window windows`，本机 HyperOS 实测
    5.5s（该命令返回空后还会再跑一次 `dumpsys activity activities`）；而
    `dumpsys window displays | grep mCurrentFocus` 只要 ~90ms，输出同一信息。
    """
    try:
        out = d.shell(["sh", "-c", "dumpsys window displays | grep -m1 mCurrentFocus"]).output
        m = _FOCUS_RE.search(out or "")
        if m:
            return {"package": m.group("pkg"), "activity": m.group("act")}
    except Exception:
        pass
    try:
        return fast_app_current(d)
    except Exception:
        return {"package": None, "activity": ""}


def cfg_serial_hint() -> str:
    """锁键回退：--serial 未给时用固定字串（本机单设备直连）。"""
    return "default"

# ---- 关键资源（上游 fast_pipeline / price_selector / orchestrator 同款）----
FLOWLAYOUT = "cn.damai:id/project_detail_perform_price_flowlayout"
LAYOUT_SKU = "cn.damai:id/layout_sku"
TV_PRICE_NAME = "cn.damai:id/tv_price_name"
BTN_BUY = "cn.damai:id/btn_buy_view"
CHECKBOX = "cn.damai:id/checkbox"
CTA_CONTAINER = "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"
SKU_MARKERS = (FLOWLAYOUT, LAYOUT_SKU, TV_PRICE_NAME)      # 上游 sku_selectors 子集
CONFIRM_TEXTS = ("确认购买", "实名观演人", "立即提交")       # 上游 _confirm_page_ready

# ---- buy_button_guard 文案护栏（照抄上游 buy_button_guard.py）----
SAFE_TEXTS = frozenset({
    "立即购买", "立即购票", "立即抢票", "立即预定", "立即预订",
    "Book Now",
    "选座购买", "购买", "抢票", "预定",
})
BLOCKED_TEXTS = frozenset({
    "预约抢票", "预约", "预售", "即将开抢", "待开售", "未开售", "提交抢票预约",
})


def cta_text_guard(root, bounds):
    """文案护栏：CTA 区域内出现 BLOCKED 文案则拒绝点击（挂已有 dump，零成本）。"""
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
        if nb[0] < x2 and nb[2] > x1 and nb[1] < y2 and nb[3] > y1:
            if text in BLOCKED_TEXTS:
                return False, f"blocked_text:{text}"
            if text in SAFE_TEXTS:
                note.append(f"safe_text:{text}")
    return True, ",".join(note) or "no_text"


def parse_bounds(s):
    return [int(x) for x in re.findall(r"\d+", s)] if s else None


def center(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def on_screen(b, w, h):
    return 0 <= b[0] < b[2] <= w and 0 <= b[1] < b[3] <= h


def point_on_screen(p, w, h):
    return (isinstance(p, (list, tuple)) and len(p) == 2
            and isinstance(p[0], int) and isinstance(p[1], int)
            and 0 <= p[0] <= w and 0 <= p[1] <= h)


def shell_taps(d, coords):
    """上游 batch_shell_taps：多条 input tap 拼进单条 shell 命令。

    走 adb 直连（d.adb_device.shell，实测 62ms）而不是 u2 服务（114ms）：
    开售瞬间 uiautomator 服务可能被页面重绘拖住，adb 通道不受影响。
    """
    if not coords:
        return
    cmd = "; ".join(f"input tap {x} {y}" for x, y in coords)
    adb = getattr(d, "adb_device", None)
    if adb is not None:
        try:
            adb.shell(cmd)
            return
        except Exception:
            pass
    d.shell(cmd)


def confirm_page_ready_u2(d) -> bool:
    """上游 _confirm_page_ready：checkbox 或三个文本标记任一命中。"""
    if d(resourceId=CHECKBOX).exists:
        return True
    for t in CONFIRM_TEXTS:
        if d(textContains=t).exists:
            return True
    return False


class Runner:
    def __init__(self, d, out: Path, expected_total: str, target_price=None):
        self.d = d
        self.out = out
        self.expected = Decimal(expected_total)
        self.target_price = target_price
        self.out.mkdir(parents=True, exist_ok=True)
        self.w, self.h = d.window_size()
        # 各阶段耗时打点：（阶段名，monotonic）；CTA 点击为基准零点
        self.marks = []

    def mark(self, name: str) -> None:
        self.marks.append((name, time.monotonic()))

    def timing_summary(self) -> str:
        if not self.marks:
            return ""
        base = next((t for n, t in self.marks if n == "cta_tap"), None)
        origin = base if base is not None else self.marks[0][1]
        lines = ["=== 耗时明细 ==="]
        prev = origin
        for n, t in self.marks:
            if n == "cta_tap":
                lines.append(f"  {n:22s} 基准零点")
                continue
            lines.append(f"  {n:22s} t+{t - origin:6.3f}s  （步长 {t - prev:6.3f}s）")
            prev = t
        return "\n".join(lines)

    def log(self, msg: str) -> None:
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        with open(self.out / "run.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def snap(self, tag: str, pixel: bool = False):
        """一次 dump + 本地解析；像素验证只在 prewarm 决策点做。"""
        xml = self.d.dump_hierarchy()
        (self.out / f"{tag}.xml").write_text(xml, encoding="utf-8")
        root = ET.fromstring(xml)
        rep = probe.analyze(root, "cn.damai", fast_app_current(self.d).get("activity", ""))
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
        """u2 快查询轮询（~50ms/轮，不 dump 不截图），异常重试。"""
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
        x, y = center(bounds)
        self.log(f"点击 {label} ({x},{y})")
        shell_taps(self.d, [(x, y)])

    # ---- Phase 2：入口等待（上游 _wait_for_purchase_entry 0.45s@0.03）----
    def wait_for_purchase_entry(self, timeout: float = 0.45):
        """入口探测：先只查票价容器一个信号（最便宜、SKU 页必有的锚点）。

        实测每轮查 3 个 marker 时，面板滑入动画期间单轮阻塞 ~0.9s；
        收敛成 1 个信号后探测本身不再是瓶颈（其余 marker 作兜底）。
        """
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.d(resourceId=FLOWLAYOUT).exists:
                return "sku_page"
            if any(self.d(resourceId=rid).exists for rid in SKU_MARKERS):
                return "sku_page"
            if confirm_page_ready_u2(self.d):
                return "order_confirm_page"
            time.sleep(0.03)
        return None

    # ---- Phase 3：SKU 单 dump 取票价+确定按钮双坐标（上游 price_selector 同款）----
    # 优先按价格文本匹配（开售后票卡有 ¥380 文本，比索引可靠；实测教训
    # 2026-11-18 sandy：预约态实测坐标开售后面板布局变了，首批点到邻档，
    # 靠重测才回到目标档）；文本匹配不到（预约态价格文本为空）才用 price_index。
    def sku_coords(self, root, target_price=None):
        price_xy = buy_xy = None
        target = str(target_price).strip() if target_price else None
        for node in root.iter("node"):
            rid = node.get("resource-id") or ""
            if buy_xy is None and rid == BTN_BUY:
                b = parse_bounds(node.get("bounds") or "")
                if b and on_screen(b, self.w, self.h):
                    buy_xy = center(b)
            if price_xy is None and rid in (FLOWLAYOUT, "cn.damai:id/layout_price"):
                cards = [
                    c for c in node
                    if c.get("class") == "android.widget.FrameLayout"
                    and c.get("clickable") == "true"
                ]
                if target:
                    for c in cards:
                        texts = " ".join(
                            (k.get("text") or "") for k in c.iter("node")
                        )
                        if target in texts and re.search(
                            r"[¥￥]\s*" + re.escape(target), texts
                        ):
                            b = parse_bounds(c.get("bounds") or "")
                            if b and on_screen(b, self.w, self.h):
                                price_xy = center(b)
                                break
                if price_xy is None and 0 <= self.price_index < len(cards):
                    b = parse_bounds(cards[self.price_index].get("bounds") or "")
                    if b and on_screen(b, self.w, self.h):
                        price_xy = center(b)
        return price_xy, buy_xy

    # ---- Phase 4：shell 批量连点直到确认页（上游 ≤0.9s 循环）----
    # 注：上游原版是 [票价, 确定, 确定] 三连点；本实现改为 [票价, 确定]
    # 两点——尾部确定点击在订单页已打开且触摸就绪时会落在「立即提交」
    # 同位 bar 上（btn_buy_view 与订单提交按钮同位），有绕过提交闸门
    # 的风险；灰按钮竞态由循环重试覆盖。这也是上游 formal 模式禁用本
    # 路径的原因之一，故不盲点第三下。
    def shell_price_and_buy_until_confirm(self, price_xy, buy_xy) -> bool:
        # price_xy=None（--preselect 预选模式）：面板已预选目标档，只点确定
        taps = [buy_xy] if price_xy is None else [price_xy, buy_xy]
        shell_end = time.monotonic() + 0.9
        while time.monotonic() < shell_end:
            shell_taps(self.d, taps)
            # 0.35s 内未见确认页就补一击：T0 首击可能撞上翻转死帧/慢响应
            # （2026-11-25 实测首击未确认 → 拖 +1.3s 进重测轮）；确认页出现即停
            poll_end = min(shell_end, time.monotonic() + 0.35)
            while time.monotonic() < poll_end:
                if confirm_page_ready_u2(self.d):
                    return True
                time.sleep(0.02)
        return False

    # ---- Phase 4 回退：元素点击（上游 _select_price_with_pipeline /
    #      _click_sku_buy_with_pipeline；本机 HyperOS 可能拒无障碍点击）----
    def element_click_price(self) -> bool:
        try:
            fl = self.d(resourceId=FLOWLAYOUT)
            if not fl.exists:
                return False
            cards = fl.child(className="android.widget.FrameLayout", clickable=True)
            if cards.count > self.price_index:
                cards[self.price_index].click()
                return True
        except Exception:
            pass
        return False

    def element_click_buy(self) -> bool:
        try:
            btn = self.d(resourceId=BTN_BUY)
            if btn.exists:
                btn.click()
                return True
        except Exception:
            pass
        return False

    # ---- Phase 5 前置：观演人 checkbox 补选（上游 _finish_confirm）----
    def finish_attendees(self, required: int | None = None) -> tuple[int, int, int]:
        """返回 (checkbox 总数, 已勾选数, shell 兜底次数)。只点未勾选的。

        上游 attendee_selector：只补选到 required_count 个（从第一个未勾选开始），
        避免多选导致订单人数/金额错位（多选会被金额闸门拦下，但白跑一轮）。
        """
        boxes = self.d(resourceId=CHECKBOX)
        n = boxes.count
        shell_fb = 0
        picked = 0
        for i in range(n):
            el = boxes[i]
            if el.info.get("checked"):
                continue
            if required is not None and picked >= required:
                break
            try:
                el.click()  # 上游元素点击优先
            except Exception:
                pass
            picked += 1
            if not el.info.get("checked"):
                # 本机实证：HyperOS 拒 u2 无障碍点击（click 成功但 checked 不变）
                b = el.info["bounds"]
                shell_taps(self.d, [center((b["left"], b["top"], b["right"], b["bottom"]))])
                shell_fb += 1
        checked = sum(
            1 for i in range(n) if boxes[i].info.get("checked")
        ) if n else 0
        return n, checked, shell_fb


def attendee_required_count(root, users) -> int:
    """需要选几位观演人（移植上游 attendee_selector）。

    优先「仅需选择 N 位」提示文本（页面权威）；否则回退 config.users 个数；
    都没有则返回 0（不强制，保持旧行为）。
    """
    for n in root.iter("node"):
        text = n.get("text") or ""
        m = re.search(r"仅需选择\s*(\d+)\s*位", text)
        if m:
            return max(1, int(m.group(1)))
    return len([u for u in (users or []) if isinstance(u, str) and u.strip()])


def order_fields_ready(rep):
    """订单页首帧字段已齐时复用刚取得的快照，避免重复 dump。"""
    order = rep.get("order") or {}
    return bool(
        order.get("submit_button")
        and order.get("quantity_text")
        and order.get("total_price_text")
    )


def add_common_args(ap) -> None:
    """两模式共用参数。"""
    ap.add_argument("--serial", default=None, help="设备序列号（单台可省略）")
    ap.add_argument("--expected-total", default="780.00", help="订单应付总额（核对闸门）")
    ap.add_argument("--submit", action="store_true", help="单次授权真实提交（默认关闭，付款永远人工）")
    ap.add_argument("--show-tag", default="libenben_780_20261128", help="提交审计记录的演出标识")
    ap.add_argument(
        "--clear-record", action="store_true",
        help="人工处理完订单后把审计记录标记为 cancelled_by_user（仅整洁审计）",
    )
    ap.add_argument(
        "--force-override-once", action="store_true",
        help="（已废弃）保留参数仅为兼容旧命令",
    )
    ap.add_argument("--cache-key", default=None, help="坐标缓存键（默认用 --show-tag）")
    ap.add_argument("--no-cache", action="store_true", help="本次不读坐标缓存（仍会写回）")
    ap.add_argument(
        "--capture-coords", action="store_true",
        help="测量模式：走到 SKU 页取坐标写缓存即停（不连点不进单）",
    )
    ap.add_argument(
        "--precapture", action="store_true",
        help="开售前预抓坐标：CTA→面板→票价/确定坐标→写缓存→BACK，不连点不下单；"
             "开售后 T0 全程零 dump",
    )
    ap.add_argument(
        "--preselect", dest="preselect", action="store_true", default=None,
        help="预约预选已设置：首批只点确定不点票价（抢票默认开，回流默认关）",
    )
    ap.add_argument(
        "--no-preselect", dest="preselect", action="store_false",
        help="关闭预选直点（首批连点含票价+确定）",
    )
    ap.add_argument(
        "--session-index", type=int, default=None,
        help="场次序号（0-based，面板从上到下）：两级面板（场次→票档）必填；"
             "场次项自绘无文本时只能按索引点选",
    )
    ap.add_argument(
        "--expect-session-date", default=None,
        help="订单页场次护栏（如 2026.11.21）：订单页文本不含该日期则 STOP 不提交",
    )


def add_rush_args(ap) -> None:
    """抢票（开售）模式参数。"""
    ap.add_argument(
        "--wait-open", metavar="HH:MM|YYYY-MM-DD HH:MM",
        help="开售等待：开售时刻前只在详情页待命，到点后才开始点击",
    )
    ap.add_argument(
        "--countdown-lead-ms", type=int, default=3000,
        help="开售前多少毫秒进入 prewarm 窗口（上游 countdown_lead_ms 默认 3000）",
    )
    ap.add_argument(
        "--ignore-clock-trust", action="store_true",
        help="时钟信任 severe 时仍然继续（默认拒绝）",
    )
    ap.add_argument("--rush", action="store_true", help="（已废弃）上游 rush 方法已成默认行为")


def add_reflow_args(ap) -> None:
    """回流（蹲守）模式参数。"""
    ap.add_argument(
        "--reflow-interval", type=float, default=2.0,
        help="监听 tick 间隔秒（默认 2.0，每 tick 一次 dump）",
    )
    ap.add_argument(
        "--reflow-refresh", type=float, default=60.0,
        help="周期性重进 SKU 刷新库存的间隔秒（默认 60；SKU 库存不自动刷新）",
    )
    ap.add_argument(
        "--reflow-max-minutes", type=float, default=120.0,
        help="监听总时长上限分钟（默认 120，超时停机）",
    )
    ap.add_argument(
        "--reflow-require-text", action="append", default=[],
        help="护栏文本（可多次）：dump 可见文本必须全部包含，否则视为落在其他场次并重进",
    )


def run(args, mode: str = "rush") -> int:
    """执行一次完整流程。mode: "rush"（开售抢票）/ "reflow"（回流蹲守）。"""
    args.reflow_watch = (mode == "reflow")
    args.wait_open = getattr(args, "wait_open", None) if mode == "rush" else None
    if args.preselect is None:
        # 抢票/预约场景默认预选直点；回流场景面板未选档（底部 ¥0），必须显式点票价
        args.preselect = not args.reflow_watch
    args.cache_key = args.cache_key or args.show_tag

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
        print(f"已把 {args.show_tag} 的 {n} 条提交记录标记为 cancelled_by_user（仅审计标记，不影响提交）")
        return 0

    import uiautomator2 as u2
    # 单实例锁（上游 runtime_lock.DeviceInstanceLock）：同一设备只允许一个运行器，
    # 非阻塞——拿不到立即停，避免两个进程互抢 UI（BACK/dump 错乱）
    lock = runtime_lock.DeviceInstanceLock(args.serial or (cfg_serial_hint()))
    if not lock.acquire():
        print("STOP: 该设备已有另一个运行器在跑（单实例锁被占用）——"
              "先停掉它（kill <pid>）再重跑")
        return 1
    d = u2.connect(args.serial)
    platform = "maoyan" if fast_app_current(d).get("package") == MY.PACKAGE else "damai"
    cfg = json.loads(re.sub(r"//[^\n]*", "", (ROOT / "config.local.jsonc").read_text("utf-8")))
    # 上游 orchestrator.py:922 —— 关闭 u2 内部等待，避免隐式阻塞
    d.settings["wait_timeout"] = 0
    d.settings["operation_delay"] = (0, 0)
    r = Runner(d, out, args.expected_total, target_price=cfg.get("price"))
    atexit.register(lambda: print(r.timing_summary()) if r.marks else None)
    if not isinstance(cfg.get("price_index"), int) or isinstance(cfg.get("price_index"), bool):
        r.log("STOP: config.local.jsonc 缺少已确认的 price_index（用向导 capture 后 apply 写入）")
        return 1
    r.price_index = int(cfg["price_index"])
    r.log(f"=== E2E 运行开始（submit={'ON' if args.submit else 'OFF'}，"
          f"expected_total={args.expected_total}，price_index={r.price_index}，"
          f"preselect={'ON' if args.preselect else 'OFF'}，"
          + (f"reflow 监听 interval={args.reflow_interval}s/refresh={args.reflow_refresh}s，"
             if args.reflow_watch else "")
          + f"上游 fast_pipeline 方法）===")

    # ---- 0) 自恢复到详情页（缓存命中时 activity 快查即可，跳过 dump）----
    if platform == "maoyan":
        for i in range(3):
            root_m, _ = r.snap(f"s0_{i}")
            st = MY.page_info(root_m)["state"]
            if st in ("detail_page", "order_confirm"):
                r.log(f"s0: 猫眼 {st}（第 {i} 次判定）")
                break
            r.log(f"s0: 当前 {st}，BACK 返回详情页")
            d.shell("input keyevent 4")
            time.sleep(0.8)
        else:
            r.log("STOP: 未回到猫眼详情页")
            return 1
    cache_ok = False
    if platform != "maoyan":
        # 大麦 s0：缓存校验 + probe 状态判定 + BACK 阶梯
        cache = None if args.no_cache else coords_cache.load(ROOT, args.cache_key)
        cache_ok = bool(
            cache
            and cache.get("screen") == [r.w, r.h]
            and cache.get("price_index") == r.price_index
            and all(point_on_screen(cache.get(k), r.w, r.h)
                    for k in ("cta_xy", "price_xy", "buy_xy"))
        )
        if cache and not cache_ok:
            r.log("s0: 坐标缓存校验未过（屏尺寸/price_index/坐标屏内）——走 dump 路径")
        if cache_ok and "ProjectDetailActivity" in fast_app_current(d).get("activity", ""):
            r.log("s0: 详情页（activity 快查）+ 缓存校验通过，跳过 dump")
        else:
            cache_ok = False
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
                else:
                    break
            if rep.get("state") != "detail_page":
                r.log(f"STOP: 不在详情页（state={rep.get('state')}）——请手动打开目标演出详情页后重跑")
                return 1
            # 恢复到详情页后，缓存校验依然成立（屏尺寸/price_index/坐标已验过）
            if cache:
                cache_ok = True
        # T0 直点坐标在这里定下来（此刻页面静止，查询安全）；开售瞬间不再查询
        startup_cta_bounds = None
        if cache_ok and cache:
            cx, cy = cache["cta_xy"]
            startup_cta_bounds = [cx - 1, cy - 1, cx + 1, cy + 1]
        else:
            root0, rep0 = r.snap("s0_cta")
            startup_cta_bounds = rep0["cta"].get("container_bounds")
            if startup_cta_bounds:
                r.log(f"s0: CTA 坐标已记（{startup_cta_bounds}）——T0 直点用，开售瞬间零查询")

    # ---- 0.4) 预抓坐标（开售前跑一次，把 SKU 坐标固化进缓存）----
    # 目的：开售后 T0 全程零 dump。实测进面板后那次 dump 会撞滑入动画，
    # 多花 0.6s（11:33 演习 0.758s vs 11:12 的 0.173s）。
    if args.precapture:
        if platform == "maoyan":
            r.log("STOP: --precapture 暂只支持大麦（猫眼每轮文本定位）")
            return 1
        root_p, rep_p = r.snap("pre_cta")
        cta_b = rep_p["cta"].get("container_bounds")
        if not cta_b:
            r.log("STOP: precapture 未找到详情页 CTA 容器")
            return 1
        r.log(f"precapture: CTA {cta_b} → 打开面板")
        r.tap(cta_b, "precapture CTA")
        entry_p = r.wait_for_purchase_entry(1.5)
        if entry_p != "sku_page":
            r.log(f"STOP: precapture 未进入面板（entry={entry_p}）")
            return 1
        price_xy = buy_xy = None
        for attempt in range(3):
            root_p, rep_p = r.snap(f"pre_sku_{attempt}")
            price_xy, buy_xy = r.sku_coords(root_p, r.target_price)
            if price_xy and buy_xy:
                break
            if attempt == 0 and (args.session_index is not None or cfg.get("date")):
                root_p, _tb = reflow.prepare_tiers(
                    d, r.log, r.price_index, args.session_index,
                    date=cfg.get("date"), city=cfg.get("city"),
                )
            time.sleep(0.3)
        if not price_xy or not buy_xy:
            r.log("STOP: precapture 未测到票价/确定坐标")
            return 1
        cxy = center(cta_b)
        coords_cache.save(ROOT, args.cache_key, {
            "cta_xy": [cxy[0], cxy[1]],
            "price_xy": list(price_xy), "buy_xy": list(buy_xy),
            "screen": [r.w, r.h], "price_index": r.price_index,
        })
        r.log(f"RESULT: ✅ 坐标已固化 price={price_xy} buy={buy_xy} "
              f"cta={cxy}（key={args.cache_key}）——开售时 T0 全程零 dump")
        d.adb_device.shell("input keyevent 4")
        time.sleep(0.6)
        return 0

    # ---- 0.5) 开售等待模式（上游 wait_for_sale_start 骨架：clock_sync + lead 轮询）----
    prewarm_ok = False
    if args.wait_open:
        raw = args.wait_open
        try:
            rough_wall = datetime.datetime.now().astimezone()
            if len(raw) > 5:
                naive = datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M")
            else:
                # strptime("%H:%M") 默认年份 1900（实测踩坑：目标落到过去、倒计时为负）
                naive = datetime.datetime.combine(
                    rough_wall.date(), datetime.datetime.strptime(raw, "%H:%M").time()
                )
        except ValueError:
            r.log(f"STOP: 无法解析开售时刻 {raw!r}（支持 HH:MM 或 YYYY-MM-DD HH:MM）")
            return 1
        obs = clock_sync.sample_clock()
        # anchor 两采样点必须紧邻且在 sample_clock 之后（实测踩坑：晚 1.77s）
        anchor_wall = datetime.datetime.now().astimezone()
        anchor_mono = time.monotonic()
        target = naive.replace(tzinfo=anchor_wall.tzinfo)
        if target <= anchor_wall:
            # 开售时刻已过：不再归到明天（2026-11-25 演习踩坑：采样耗时 17s，
            # 10:10 被归到次日 10:10，静默挂 24h）。HH:MM 一律指今天，
            # 已过就立即开跑（晚到就抢，不等明天）
            r.log(f"clock: 开售时刻已过 {(anchor_wall - target).total_seconds():.0f}s——立即开跑")
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
        while True:
            remaining = dl.remaining_seconds(time.monotonic())
            if remaining <= lead:
                break
            time.sleep(min(0.05, remaining - lead))
        prewarm_bounds = startup_cta_bounds if args.wait_open else None
        if platform == "maoyan":
            while True:
                remaining = dl.remaining_seconds(time.monotonic())
                if remaining <= 0:
                    break
                time.sleep(min(0.05, remaining))
            r.log("wait-open: 到点（猫眼，无 prewarm）")
            prewarm_ok = False
        else:
            # 开售热路径零设备查询（2026-11-23 两次实战教训）：
            # T0-3s 做的任何 u2/dumpsys 查询，在页面从预约态翻到开售态期间
            # 可能阻塞 20-30s（实测 22.8s / 30s+），直接错过开售。
            # 坐标一律用 s0 阶段（页面静止时）记下的 CTA 坐标。
            if prewarm_bounds:
                prewarm_ok = True
                r.log(f"wait-open: T0 直点就绪（坐标 {prewarm_bounds}，来自 s0；"
                      "开售瞬间零查询）")
            else:
                prewarm_ok = False
                r.log("wait-open: 无可用 CTA 坐标——T0 后走验证路径")
        while True:
            remaining = dl.remaining_seconds(time.monotonic())
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))
        r.log("wait-open: 到点，进入点击窗口")
        # T0 直点前廉价闸门（上游 _scheduled_sale_click_gate 思路）：只验 activity
        # 注：上游此处有 _scheduled_sale_click_gate（activity 校验），本实现**去掉**：
        # T0 那一刻任何设备查询都可能阻塞（2026-11-23 实测 20-30s），而坐标来自
        # s0 阶段、点击是盲点，多一次校验只增加错过开售的风险。

    # ---- 回流票监听模式外层轮次（上游 run_with_retry 轮次模型）----
    # 非回流模式恰好跑一轮；回流模式下本轮提交后售罄（可重试失败）→ 回监听继续蹲；
    # 不可重试失败（验证码/待支付归属不了/结果未知）仍然停机
    reflow_active = args.reflow_watch
    reflow_round = 0
    while True:
        if reflow_round:
            # 二次回流：从售罄页 BACK 回详情页，Phase1 重新进 SKU（重进即刷新库存）
            for _ in range(4):
                act = fast_app_current(d).get("activity", "")
                if "projectdetail" in act.lower():
                    break
                d.shell("input keyevent 4")
                time.sleep(0.5)
            r.log(f"== 回流第 {reflow_round + 1} 轮：重新进入监听 ==")
        # ---- 猫眼：同一套阶段，只换定位（文本→最近可点击祖先）----
        if platform == "maoyan":
            root_m, _ = r.snap("s1_maoyan")
            info = MY.page_info(root_m)
            if info["state"] == "order_confirm":
                r.log("s1: 猫眼已在订单页——跳过 CTA/面板，直接核对")
                cta = {"blocked_text": None, "safe_to_click": False, "text": "已在订单页"}
                return _maoyan_order_step(d, r, root_m, info, args)
            cta = info["cta"]
            if not cta:
                r.log("STOP: 猫眼未找到底部购票 CTA")
                return 1
            r.log(f"s1: 猫眼 CTA {cta['text']!r} 可点={cta['safe_to_click']} "
                  f"阻断词={cta['blocked_text']}")
            if not cta["safe_to_click"] and not getattr(args, "simulate", False):
                r.log("STOP: CTA 处于预约/未开售态——默认不点；模拟演练加 --simulate")
                return 1
            r.tap(cta["bounds"], "猫眼购票 CTA")
            r.mark("cta_tap")
            # Phase 2：入口等待（猫眼面板比大麦慢，放宽到 3s；不做 dump 判定）
            tiers = None
            end_wait = time.monotonic() + 3.0
            while time.monotonic() < end_wait:
                root_m, _ = r.snap("s2_maoyan")
                info = MY.page_info(root_m)
                tiers = info["tiers"]
                if tiers:
                    break
                time.sleep(0.1)
            if not tiers:
                r.log("STOP: 猫眼面板未出现票档（入口等待 3s 超时）")
                return 1
            r.mark("entry_sku_page")
            r.log(f"s1: 进入猫眼面板（票档 {len(tiers)} 档）")
            # Phase 3：选档（预选模式跳过，与大麦一致）
            if not args.preselect:
                price_want = str(cfg.get("price") or "")
                target = next((t for t in tiers if t["price"] == price_want), None)
                if target is None:
                    idx = cfg.get("price_index")
                    if isinstance(idx, int) and 0 <= idx < len(tiers):
                        target = tiers[idx]
                if target is None:
                    r.log(f"STOP: 猫眼未匹配到目标票档（price={price_want}）")
                    return 1
                r.log(f"s2: 猫眼票价 {target['name']!r} ¥{target['price']} → 点击")
                r.tap(target["bounds"], f"票档 ¥{target['price']}")
            else:
                r.log("s2: 预选模式——跳过选档（预约已带入目标档）")
            r.mark("coords_ready")
            # Phase 4：确定（开售后是购买按钮；预约态是底部「已预约」）
            conf = MY.extract_confirm(root_m) or MY.bottom_button(root_m)
            if conf is None:
                r.log("STOP: 猫眼底部未找到确定/购买按钮")
                return 1
            r.tap(conf["bounds"], f"确定 {conf.get('hit') or conf.get('text')}")
            r.mark("batch1_done")
            time.sleep(1.2)
            # Phase 5：结果判定（只读）
            root_m, _ = r.snap("s5_maoyan")
            blob = MY.page_info(root_m)["blob"]
            if "日历提醒" in blob:
                r.log("RESULT: ✅ 猫眼预约态终点——弹出日历提醒（开售时间见弹层）")
                r.mark("done_no_confirm")
                return 0
            if not any(k in blob for k in MY.ORDER_MARKERS):
                if cta["blocked_text"]:
                    r.log(f"RESULT: ✅ 猫眼流程完成（预约态：CTA={cta['blocked_text']}，"
                          f"无订单页，开售后才有提交步骤）")
                    r.mark("done_no_confirm")
                    return 0
                r.log("STOP: 猫眼未进入订单页")
                return 1
            return _maoyan_order_step(d, r, root_m, MY.page_info(root_m), args)

        # ---- Phase 1+2：CTA 点击（prewarm T0 直点 > 缓存坐标 > 单 dump）+ 入口等待 ----
        entered_order = False
        entry = None
        fresh_cta = None
        if args.wait_open and prewarm_ok:
            cta_b = prewarm_bounds or (cache["cta_xy"] and [
                cache["cta_xy"][0] - 1, cache["cta_xy"][1] - 1,
                cache["cta_xy"][0] + 1, cache["cta_xy"][1] + 1,
            ])
            r.tap(cta_b, "详情页购票 CTA（prewarm T0 直点）")
            r.mark("cta_tap")
            fresh_cta = center(cta_b)
            r.mark("s0_ready")
            # T0 驻留锚点 = CTA 点击时刻（不是入口确认时刻）：翻转期入口探测本身
            # 要 0.3-0.5s，再叠加 0.4s 驻留会把首击拖到 T+0.9（2026-11-25 实测）。
            # 驻留从点击起算 0.4s，探测剩余时间自然覆盖；首击若被吞由连点补击兜住
            r.marks_entry = time.monotonic()
            entry = r.wait_for_purchase_entry(3.0)
            if entry is None:
                r.log("wait-open: T0 直点未进页，回退 Phase1 验证路径")
        elif cache_ok:
            xy = tuple(cache["cta_xy"])
            r.log(f"s1: 缓存 CTA 坐标 {xy} 直点（跳过 dump；入口轮询+订单核对兜底）")
            shell_taps(d, [xy])
            r.mark("cta_tap")
            entry = r.wait_for_purchase_entry(0.45)
            if entry is None:
                r.log("s1: 缓存坐标未进页，双击重试（上游 _open_purchase_panel）")
                shell_taps(d, [xy, xy])
                entry = r.wait_for_purchase_entry(0.45)
            if entry is None:
                r.log("s1: 缓存坐标未进页，回退 dump 路径")
        if entry is None:
            # 上游 rush_preselect_and_buy_via_xml：单 dump → CTA 坐标 → shell 点击
            root, rep = r.snap("s1_detail")
            cta_b = rep["cta"].get("container_bounds")
            if not cta_b:
                r.log("STOP: 详情页未找到购票 CTA 容器")
                return 1
            allow, note = cta_text_guard(root, cta_b)
            if not allow:
                r.log(f"STOP: CTA 文案护栏拦截（{note}）——疑似预约/预售态，不点击")
                return 1
            if note and note != "no_text":
                r.log(f"s1: CTA 文案护栏通过（{note}）")
            r.tap(cta_b, "详情页购票 CTA")
            r.mark("cta_tap")
            fresh_cta = center(cta_b)
            entry = r.wait_for_purchase_entry(0.45)
            if entry is None:
                # 上游 _open_purchase_panel 回退：shell 双击再等一次
                r.log("s1: 入口等待超时，回退 CTA 双击重试")
                shell_taps(d, [center(cta_b), center(cta_b)])
                entry = r.wait_for_purchase_entry(0.45)
        if entry is None:
            r.log("STOP: CTA 点击后未进入 SKU/订单页")
            return 1
        r.mark(f"entry_{entry}")
        if not getattr(r, "marks_entry", None):
            r.marks_entry = time.monotonic()
        if entry == "order_confirm_page":
            entered_order = True
            r.log("s1: 直达订单确认页（未展开 SKU）")
        else:
            r.log("s1: 进入 SKU 页（入口快查询确认）")
        # ---- 回流监听：目标票档缺货登记在屏 → 监听直到可购信号 ----
        if reflow_active and entry == "sku_page":
            # 两级面板（场次→票档）：无票档时按 --session-index 点选场次
            root, tb = reflow.prepare_tiers(
                d, r.log, r.price_index, args.session_index,
            )
            if tb is None:
                r.log(f"STOP: 回流监听无法定位目标票档（price_index={r.price_index}）")
                return 1
            if reflow.tier_is_unavailable(root, tb):
                r.log(f"reflow: 目标票档当前不可购（缺货登记在屏），进入监听"
                      f"（interval={args.reflow_interval}s，refresh={args.reflow_refresh}s，"
                      f"上限 {args.reflow_max_minutes:.0f}min）")
                res = reflow.watch(
                    d, r.log, price_index=r.price_index,
                    cta_xy=fresh_cta or (tuple(cache["cta_xy"]) if cache_ok else None),
                    session_index=args.session_index,
                    interval=args.reflow_interval, refresh_every=args.reflow_refresh,
                    require_texts=tuple(args.reflow_require_text),
                    deadline_mono=time.monotonic() + args.reflow_max_minutes * 60.0,
                )
                if res["status"] != "ready":
                    r.log(f"STOP: 回流监听超时（{res['tick']} ticks）——未等到回流")
                    return 1
                r.mark("reflow_ready")

        # ---- Phase 3+4：坐标（缓存 > 单 dump）→ shell 批量连点（含自愈重测）----
        if args.capture_coords and entered_order:
            r.log("RESULT: 直达订单确认页，SKU 坐标无需测量，未写缓存")
            return 0
        if not entered_order:
            price_xy = buy_xy = None
            if cache_ok and entry == "sku_page":
                price_xy, buy_xy = tuple(cache["price_xy"]), tuple(cache["buy_xy"])
                if args.preselect:
                    r.log(f"s2: 预选模式：跳过选档，缓存确定按钮 {buy_xy}（预约预选已带入面板）")
                else:
                    r.log(f"s2: 缓存坐标 票价{price_xy} 确定{buy_xy}（跳过 SKU dump）")
                # 实测（2026-11-18）：入口确认后 ~1ms 连点被页面吞掉（3/4 失败），
                # dump 路径天然时延 0.35-1.2s 从未失败；补足到「入口后 0.4s」驻留，
                # 入口探测本身已耗时则不再等（避免 0.9s 探测 + 0.4s 驻留叠加）。
                # T0 直点路径 marks_entry 已在 CTA 点击时刻赋值（见 Phase1+2）
                elapsed = time.monotonic() - getattr(r, "marks_entry", 0.0)
                if elapsed < 0.4:
                    time.sleep(0.4 - elapsed)
                r.mark("settle_done")
            if price_xy is None:
                root, rep = r.snap("s2_sku")
                price_xy, buy_xy = r.sku_coords(root, r.target_price)
                if price_xy is None:
                    # 上游 price_selector：卡片可能未加载完，0.3s 后重 dump 一次
                    time.sleep(0.3)
                    root, rep = r.snap("s2_sku_retry")
                    price_xy, buy_xy = r.sku_coords(root, r.target_price)
                if price_xy is None and (args.session_index is not None or cfg.get("date")):
                    # 两级面板（场次→票档）：预约预选未生效时面板先显示场次列表，
                    # 票档根本不在树里。按 --session-index / config.date 点选场次后重测。
                    r.log("s2: 未发现票档容器（疑似两级面板场次层），尝试选场次后重测")
                    root, tb = reflow.prepare_tiers(
                        d, r.log, r.price_index, args.session_index,
                        date=cfg.get("date"), city=cfg.get("city"),
                    )
                    if tb is not None:
                        price_xy, buy_xy = r.sku_coords(root, r.target_price)
                        cache_ok = False  # 面板已重选场次，旧缓存坐标不可信
                if price_xy is None or buy_xy is None:
                    r.log(f"STOP: SKU 坐标缺失（price_index={r.price_index}，"
                          f"price={price_xy}, buy={buy_xy}）——票档序号可能超出实际票卡数")
                    return 1
                r.log(f"s2: 票价 {price_xy}，确定按钮 {buy_xy}（单 dump 双坐标）")
            if args.capture_coords:
                coords_cache.save(ROOT, args.cache_key, {
                    "cta_xy": list(fresh_cta or cache["cta_xy"]),
                    "price_xy": list(price_xy), "buy_xy": list(buy_xy),
                    "screen": [r.w, r.h], "price_index": r.price_index,
                })
                r.log(f"RESULT: ✅ 坐标已缓存（key={args.cache_key}）——测量模式到此为止，"
                      "未连点未进单")
                return 0
            r.mark("coords_ready")
            confirmed = r.shell_price_and_buy_until_confirm(
                None if args.preselect else price_xy, buy_xy
            )
            r.mark("batch1_done")
            path = "shell批量连点" + ("（预选直点确定）" if args.preselect else "")
            if not confirmed and cache_ok and list(price_xy) == cache["price_xy"]:
                # 自愈：入口即连点可能被页面吞掉（实测 ~1/3 概率）——重测坐标；
                # 坐标没变也再连点一轮：此时距入口 ~1.5s，是 dump 路径屡试
                # 不爽的时延区；仍失败才走元素回退
                r.log("s2: 缓存坐标未确认，重测后再连点一轮")
                root, rep = r.snap("s2_remeasure")
                p2, b2 = r.sku_coords(root, r.target_price)
                if p2 and b2:
                    price_xy, buy_xy = p2, b2
                    # 预选模式首轮只点了确定；重测后用文本匹配票价+确定全量连点
                    # （预选万一未生效，开售后价格文本已渲染，文本匹配可靠）
                    if r.shell_price_and_buy_until_confirm(price_xy, buy_xy):
                        confirmed = True
                        path = "shell连点（重测后）"
                    r.mark("batch2_done")
            if not confirmed:
                r.log("s2: shell 路未确认，元素点击回退")
                price_ok = True if args.preselect else r.element_click_price()
                if price_ok and r.element_click_buy():
                    poll_end = time.monotonic() + 0.55   # 上游 _wait_for_confirm_ready
                    while time.monotonic() < poll_end:
                        if confirm_page_ready_u2(d):
                            confirmed = True
                            break
                        time.sleep(0.02)
                if path == "shell批量连点":
                    path = "元素点击回退"
            if not confirmed:
                r.log("STOP: 确认页未出现（连点+重测+元素回退均超时）——可能票档不可选/弹窗拦截")
                return 1
            r.mark("order_confirm")
            r.log(f"s2: 到达订单确认页（{path}）")
            # 到单成功 → 刷新缓存（本次实际生效的坐标）
            coords_cache.save(ROOT, args.cache_key, {
                "cta_xy": list(fresh_cta or cache["cta_xy"]),
                "price_xy": list(price_xy), "buy_xy": list(buy_xy),
                "screen": [r.w, r.h], "price_index": r.price_index,
            })
            r.log("s2: 坐标缓存已刷新")

        # ---- Phase 5：观演人 checkbox 补选（上游 _finish_confirm）→ 全字段核对 ----
        root, rep = r.snap("s2_after")
        if rep["state"] != "order_confirm_page":
            r.log(f"STOP: 确认后状态异常（state={rep['state']}）")
            return 1
        # 需要几位观演人（上游 attendee_selector：优先「仅需选择 N 位」）
        users_cfg = [u.strip() for u in (cfg.get("users") or []) if isinstance(u, str) and u.strip()]
        required_attendees = attendee_required_count(root, users_cfg)
        # checkbox 状态直读已有快照：全勾则跳过 u2 逐个 .info（实测省 ~0.8s）
        cb_states = [n.get("checked") == "true" for n in root.iter("node")
                     if (n.get("resource-id") or "") == CHECKBOX]
        if cb_states and all(cb_states):
            n_box = checked = len(cb_states)
            shell_fb = 0
            r.log(f"s3: 观演人 checkbox {checked}/{n_box} 已勾选（XML 直读）")
        else:
            n_box, checked, shell_fb = r.finish_attendees(required=required_attendees or None)
            r.log(f"s3: 观演人 checkbox {checked}/{n_box} 已勾选"
                  + (f"（元素点击失效 {shell_fb} 个→shell 兜底）" if shell_fb else ""))
        # 首帧字段已齐则复用 s2_after 快照核对，免重复 dump
        r.mark("attendees_done")
        if not order_fields_ready(rep):
            root, rep = r.wait_until(
                lambda rt, p: order_fields_ready(p),
                "s3_load", timeout=3.0, poll_interval=POLL_FAST,
            )
        if root is None:
            r.log(f"STOP: 订单字段未在有界时间内就绪（order={rep.get('order')}）")
            return 1
        order = rep["order"]
        m = re.fullmatch(r"¥\s*([\d,]+(?:\.\d{1,2})?)", order.get("total_price_text") or "")
        amount = Decimal(m.group(1).replace(",", "")) if m else None
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
            "attendees_checked": checked,
            "attendees_checked_match": (not users_cfg and not required_attendees)
            or checked >= max(required_attendees, len(users_cfg)),
        }
        # 场次护栏（两级面板防错场次）：订单页文本必须含目标日期
        if args.expect_session_date:
            order_texts = [
                (n.get("text") or "").strip() for n in root.iter("node")
            ]
            checks["session_date"] = args.expect_session_date
            # 归一化后再比：配置写 11-28、订单页显示 2026.11.28 也算过
            # （2026-11-25 实战因横杠/点号不一致拦停正确订单）
            norm = lambda s: (s or "").replace("-", ".")
            checks["session_date_match"] = any(
                norm(args.expect_session_date) in norm(t) for t in order_texts
            )
        ok = all((checks["submit_button_visible"], checks["quantity"] == "×1张",
                  checks["amount_match"], checks["attendees_match"],
                  checks["attendees_checked_match"],
                  checks.get("session_date_match", True)))
        r.mark("verified")
        r.log("s3: 订单核对 " + json.dumps(checks, ensure_ascii=False))
        if not ok:
            r.snap("s3_final")
            r.log("RESULT: ❌ 到达订单页但核对未全通过——停机，交人工检查")
            return 1
        if not args.submit:
            r.snap("s3_final")
            r.mark("done_no_submit")
            r.log("RESULT: ✅ 端到端（无提交）通过——已到订单页且全字段核对一致，停在提交前")
            return 0

        # ---- 3.5) 提交前 overlay 筛查（上游 _submit_order_fast 同构；复用核对
        # dump 零额外耗时）：验证/待支付弹窗即停不提交；瞬时错误先恢复再提交。
        # 防的是「弹窗已在屏上时盲点提交」（点击会落在弹窗层而非提交按钮）----
        pre = recovery.inspect_transient_failure(
            root, "cn.damai", fast_app_current(d).get("activity", "")
        )
        # 授权弹窗（上游 probe_consent_dialog 同构：资源 ID 直查，非文本）
        if any(
            (n.get("resource-id") or "") == "cn.damai:id/id_boot_action_agree"
            for n in root.iter("node")
        ):
            r.log("STOP: 提交前检测到授权弹窗（上游 consent_dialog）——不点击提交，交人工")
            return 1
        if pre["manual_verification"]:
            r.log("STOP: 提交前检测到验证码/人机验证——不点击提交，交人工")
            return 1
        if pre["pending_order"]:
            r.log("STOP: 提交前检测到待支付订单弹窗——无法归属本次运行，不点击提交")
            return 1
        if pre["transient"]:
            r.log("s4: 提交前页面处于瞬时错误态，先走恢复再提交")
            rec = recovery.recover_transient_failure(
                d, r.log, max_attempts=2, acted_fingerprints=set(),
            )
            if not rec.get("recovered"):
                r.log("STOP: 提交前瞬时错误恢复失败——不点击提交")
                return 1
            root, rep = r.snap("s4_after_recovery")
            if not order_fields_ready(rep):
                r.log("STOP: 恢复后订单字段未就绪——不点击提交")
                return 1
            order = rep["order"]

        # ---- 4) 提交（审计记录，不拦截）：订单是否已处理由用户人工确认，
        # 大麦 App 自身有「已有待支付订单」拦截；记录仅留审计/取证用途 ----
        gate = ROOT / "logs" / "submit_record.json"
        records = json.loads(gate.read_text(encoding="utf-8")) if gate.exists() else []
        prior_unpaid = [
            x for x in records
            if x.get("show_tag") == args.show_tag
            and x.get("status") == "awaiting_user_payment"
        ]
        if prior_unpaid:
            r.log(f"⚠️ 注意：此前有一笔待支付提交（{prior_unpaid[-1]['time']}）——"
                  "若未处理，大麦会以「已有待支付订单」拦截本次提交")
        records.append({
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "show_tag": args.show_tag,
            "status": "submitted_intent",
            "amount": str(amount),
            "evidence": out.name,
        })
        gate.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        r.log("s4: 点击『立即提交』（提交前核对已全过）——此后不盲重试，到收银台即停")
        r.tap(order["submit_button"]["bounds"], "立即提交")
        r.mark("submit_tap")

        # ---- 5) 提交后结果验证（上游 verify_order_result 同构：只读
        # fail-closed——提交点击后不再发出任何点击，防重复下单）。
        # 实测（2026-11-18 sandy 开售）：提交后大麦可能停在 DmOrderActivity
        # 「提交中」超过 8s，之后才跳收银台；观察窗口放宽到 20s（上游默认 5s）
        sold_out_this_round = False
        deadline = time.monotonic() + 20.0
        act = ""
        # 上游 verify_order_result 词表（逐字移植）
        payment_text_markers = ("立即支付", "去支付", "确认支付", "支付剩余时间", "收银台")
        payment_activities = ("payactivity", "cashier", "alipayclient", "paymentactivity")
        sold_out_markers = ("已售罄", "库存不足", "暂时无票")
        captcha_markers = ("滑块", "人机验证", "安全验证", "验证码")
        last_dump = 0.0
        while time.monotonic() < deadline:
            act = fast_app_current(d).get("activity", "")
            act_key = act.casefold()
            now = time.monotonic()
            # 只读观察：~0.5s 一次 dump 取全页文本，分类但不点击（上游 0.3s 粒度）
            merged = ""
            if now - last_dump >= 0.5:
                last_dump = now
                try:
                    root5 = ET.fromstring(d.dump_hierarchy())
                    merged = " ".join(
                        (n.get("text") or "").strip()
                        for n in root5.iter("node")
                        if n.get("visible-to-user") != "false"
                        and (n.get("text") or "").strip()
                    )
                except Exception:
                    root5, merged = None, ""
            if any(m in act_key for m in payment_activities):
                if root5 is not None and any("滑块" in t or "安全验证" in t for t in merged.split()):
                    r.log("STOP: 收银台出现验证拦截——红线，交人工")
                    return 1
                records[-1]["status"] = "awaiting_user_payment"
                gate.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
                r.mark("cashier")
                r.log("RESULT: ✅ 提交成功到达收银台——待用户支付，流程终止")
                return 0
            if merged:
                if any(m in merged for m in sold_out_markers):
                    if reflow_active:
                        records[-1]["status"] = "sold_out"
                        gate.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
                        r.log("s5: 本轮提交后售罄（上游 sold_out）——二次回流：回监听继续蹲")
                        sold_out_this_round = True
                        break
                    r.log("STOP: 提交后页面显示票已售罄（上游 sold_out）——停止，交人工")
                    return 1
                if any(m in merged for m in captcha_markers):
                    r.log("STOP: 提交后触发验证码/人机验证（上游 captcha）——红线，交人工")
                    return 1
                if "未支付" in merged:
                    r.log("STOP: 检测到未支付订单但无法归属本次提交（上游 preexisting_order）"
                          "——停止自动操作，请人工核实订单列表")
                    return 1
                if any(m in merged for m in payment_text_markers):
                    records[-1]["status"] = "awaiting_user_payment"
                    gate.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
                    r.mark("cashier")
                    r.log("RESULT: ✅ 检测到支付页信号——待用户支付，流程终止")
                    return 0
            time.sleep(POLL_PAGE)
        if sold_out_this_round:
            reflow_round += 1
            continue
        # 上游同款 fail-closed：结果未知，绝不二次点击
        records[-1]["status"] = "result_unknown"
        gate.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        r.log(f"STOP: 订单验证超时（activity={act.split('.')[-1]}，上游 timeout）——"
              "结果未知，不二次点击；请在大麦「我的→待付款/订单列表」人工核实")
        return 1
