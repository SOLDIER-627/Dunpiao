#!/usr/bin/env python3
"""旁路-02：完全复刻上游 HaTickets fast_pipeline 的端到端方法（无提交）。

仅新增文件，不碰 e2e_run.py / probe.py。目的：在本机真机上实测
「上游 rush 方法」的原样效果，与本仓库 rush/stable 两版对比。

忠实复刻的上游机制（fast_pipeline.run_cold_validation + price_selector）：
  Phase 1 详情页   单次 dump → CTA 容器坐标 → shell input tap
  Phase 2 入口等待 轮询 SKU 页标记（flowlayout / layout_sku / tv_price_name）0.45s@0.03
  Phase 3 SKU 页   单次 dump → 票价卡中心（flowlayout 子 FrameLayout+clickable，
                   取 config.price_index）+ btn_buy_view 中心
  Phase 4 shell 连点  _shell_price_and_buy_until_confirm：单条 shell 命令
                   依次 input tap [票价, 确定, 确定]，循环 ≤0.9s，
                   确认判定 = checkbox / 确认购买 / 实名观演人 / 立即提交（0.02s 粒度）
  回退             元素点击票价（u2 无障碍 click）→ 元素点击确定 → 0.55s 确认轮询
  收尾             观演人 checkbox 逐个点击（元素 click，失败回退 shell tap），
                   停在「立即提交」前——绝不自动提交（合规红线）

与上游的差异（均为本机约束，非方法偏离）：
  - 起点自恢复：上游由外层调度保证在详情页；本脚本先用 BACK 阶梯回到详情页
  - 不提交：上游 if_commit_order=False 同款行为；本脚本永远停提交前
  - 证据落盘：logs/upstream_<ts>/（上游仅临时 dump；本仓库审计要求留证）
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import uiautomator2 as u2

ROOT = Path(__file__).resolve().parents[1]
FLOWLAYOUT = "cn.damai:id/project_detail_perform_price_flowlayout"
LAYOUT_SKU = "cn.damai:id/layout_sku"
TV_PRICE_NAME = "cn.damai:id/tv_price_name"
BTN_BUY = "cn.damai:id/btn_buy_view"
CHECKBOX = "cn.damai:id/checkbox"
CTA_CONTAINER = "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"

SKU_MARKERS = (FLOWLAYOUT, LAYOUT_SKU, TV_PRICE_NAME)  # 上游 sku_selectors 子集


def log(t0: float, msg: str) -> None:
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
          f"  (+{time.monotonic() - t0:.3f}s)", flush=True)


def parse_bounds(s: str):
    m = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", s or "")
    return tuple(int(v) for v in m.groups()) if m else None


def center(b) -> tuple[int, int]:
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


class Upstream:
    """上游 FastPipeline 的单设备 uiautomator2 等价实现。"""

    def __init__(self, d: u2.Device, out: Path, price_index: int):
        self.d = d
        self.out = out
        self.price_index = price_index
        d.settings["wait_timeout"] = 0
        d.settings["operation_delay"] = (0, 0)
        self.w, self.h = d.window_size()

    # ---- 上游 bot 原语 ----
    def dump_xml(self) -> ET.Element | None:
        xml = self.d.dump_hierarchy()
        if not xml:
            return None
        return ET.fromstring(xml)

    def has_element(self, rid: str) -> bool:
        return self.d(resourceId=rid).exists

    def shell_taps(self, coords: list[tuple[int, int]]) -> None:
        """上游 batch_shell_taps：多条 input tap 拼进单条 shell。"""
        if coords:
            self.d.shell("; ".join(f"input tap {x} {y}" for x, y in coords))

    def tap(self, xy: tuple[int, int], duration_ms: int | None = None) -> None:
        """上游 _click_coordinates(duration=25)：swipe 当 tap 带时长。"""
        if duration_ms:
            self.d.shell(f"input swipe {xy[0]} {xy[1]} {xy[0]} {xy[1]} {duration_ms}")
        else:
            self.d.shell(f"input tap {xy[0]} {xy[1]}")

    def confirm_page_ready(self) -> bool:
        """上游 _confirm_page_ready：checkbox 或三个文本标记任一命中。"""
        if self.d(resourceId=CHECKBOX).exists:
            return True
        for t in ("确认购买", "实名观演人", "立即提交"):
            if self.d(textContains=t).exists:
                return True
        return False

    # ---- Phase 1：详情页单 dump 取 CTA 坐标 ----
    def rush_preselect_and_buy(self, t0: float) -> tuple[int, int] | None:
        root = self.dump_xml()
        if root is None:
            return None
        (self.out / "s1_detail.xml").write_bytes(ET.tostring(root))
        for node in root.iter("node"):
            rid = node.get("resource-id", "")
            if rid in (CTA_CONTAINER, CTA_CONTAINER.split("cn.damai:id/")[-1]):
                b = parse_bounds(node.get("bounds", ""))
                if b:
                    xy = center(b)
                    log(t0, f"Phase1: CTA 容器坐标 {xy}，shell 点击")
                    self.tap(xy, duration_ms=25)
                    return xy
        return None

    # ---- Phase 2：入口等待（上游 0.45s@0.03，u2 exists 轮询）----
    def wait_for_purchase_entry(self, t0: float, timeout: float = 0.45):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if any(self.has_element(rid) for rid in SKU_MARKERS):
                return "sku_page"
            if self.confirm_page_ready():
                return "order_confirm_page"
            time.sleep(0.03)
        return None

    # ---- Phase 3：SKU 单 dump 取票价+确定按钮坐标 ----
    def sku_coords_from_xml(self, root: ET.Element):
        price_xy = buy_xy = None
        for node in root.iter("node"):
            rid = node.get("resource-id", "")
            if buy_xy is None and rid in (BTN_BUY, BTN_BUY.split("cn.damai:id/")[-1]):
                b = parse_bounds(node.get("bounds", ""))
                if b:
                    buy_xy = center(b)
            if price_xy is None and rid in (FLOWLAYOUT, "cn.damai:id/layout_price"):
                cards = [
                    c for c in node
                    if c.get("class") == "android.widget.FrameLayout"
                    and c.get("clickable") == "true"
                ]
                if 0 <= self.price_index < len(cards):
                    b = parse_bounds(cards[self.price_index].get("bounds", ""))
                    if b:
                        price_xy = center(b)
        return price_xy, buy_xy

    # ---- Phase 4：shell 连点直到确认页（上游 ≤0.9s 循环）----
    def shell_price_and_buy_until_confirm(self, price_xy, buy_xy, t0: float) -> bool:
        shell_end = time.monotonic() + 0.9
        while time.monotonic() < shell_end:
            self.shell_taps([price_xy, buy_xy, buy_xy])
            poll_end = min(shell_end, time.monotonic() + 0.9)
            while time.monotonic() < poll_end:
                if self.confirm_page_ready():
                    return True
                time.sleep(0.02)
        return False

    # ---- 回退：元素点击（上游 _select_price_with_pipeline / _click_sku_buy_with_pipeline）----
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

    # ---- 收尾：观演人 checkbox（上游 _finish_confirm，元素点击优先）----
    def finish_confirm(self, t0: float) -> tuple[int, int]:
        boxes = self.d(resourceId=CHECKBOX)
        n = boxes.count
        shell_fallback = 0
        for i in range(n):
            el = boxes[i]
            try:
                el.click()          # 上游元素点击优先
            except Exception:
                pass
            if not el.info.get("checked"):
                # 本机实证：HyperOS 拒 u2 无障碍点击（click 返回成功但
                # checked 不变），shell tap 兜底（上游 warm 路径同款）
                b = el.info["bounds"]
                self.shell_taps([center((b["left"], b["top"], b["right"], b["bottom"]))])
                shell_fallback += 1
        log(t0, f"收尾: 观演人 checkbox {n} 个（元素点击失效 {shell_fallback} 个→shell 补点）")
        return n, shell_fallback


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=None)
    ap.add_argument("--price-index", type=int, default=None,
                    help="缺省读 config.local.jsonc 的 price_index")
    ap.add_argument("--entry-timeout", type=float, default=0.45,
                    help="Phase2 入口等待（上游固定 0.45s）")
    ap.add_argument("--expected-total", default="780.00")
    args = ap.parse_args()

    cfg = json.loads(re.sub(r"//[^\n]*", "", (ROOT / "config.local.jsonc").read_text("utf-8")))
    price_index = args.price_index if args.price_index is not None else int(cfg["price_index"])
    expected_total = float(args.expected_total)
    d = u2.connect(args.serial)
    out = ROOT / "logs" / f"upstream_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    up = Upstream(d, out, price_index)
    t0 = time.monotonic()
    log(t0, f"=== 上游方法端到端（无提交，price_index={price_index}）===")

    # 起点自恢复（上游由外层调度保证；本机用 BACK 阶梯直到详情页）
    for _ in range(6):
        cur = d.app_current()
        act = cur.get("activity", "")
        pkg = cur.get("package", "")
        if "ProjectDetailActivity" in act:
            break
        if "damai" in pkg:
            d.press("back"); time.sleep(0.8)
        else:
            d.app_start("cn.damai"); time.sleep(1.5)
    act = d.app_current().get("activity", "")
    log(t0, f"起点 activity={act.rsplit('.', 1)[-1]}")
    if "NcovSkuActivity" in act:
        log(t0, "STOP: 仍在 SKU 页，无法开始")
        return 1

    # Phase 1：详情页 CTA
    cta = up.rush_preselect_and_buy(t0)
    if cta is None:
        log(t0, "STOP: 详情页未找到购票 CTA 容器")
        return 1
    entry = up.wait_for_purchase_entry(t0, args.entry_timeout)
    if entry is None:
        # 上游 _open_purchase_panel 回退：shell 双击再等一次
        log(t0, "Phase2 超时，回退：CTA 双击重试")
        up.shell_taps([cta, cta])
        entry = up.wait_for_purchase_entry(t0, 0.45)
    if entry is None:
        log(t0, "STOP: CTA 点击后未进入 SKU/订单页")
        return 1
    if entry == "order_confirm_page":
        log(t0, "RESULT: 直接到达订单页（CTA 未展开 SKU）")
        return 0
    log(t0, "Phase2: 进入 SKU 页")

    # Phase 3：SKU 单 dump 取双坐标
    root = up.dump_xml()
    if root is None:
        log(t0, "STOP: SKU dump 失败")
        return 1
    (out / "s2_sku.xml").write_bytes(ET.tostring(root))
    price_xy, buy_xy = up.sku_coords_from_xml(root)
    if price_xy is None:
        time.sleep(0.3)                      # 上游：卡片可能未加载完，0.3s 后重 dump 一次
        root = up.dump_xml()
        price_xy, buy_xy = up.sku_coords_from_xml(root) if root else (None, None)
    if price_xy is None or buy_xy is None:
        log(t0, f"STOP: SKU 坐标缺失（price={price_xy}, buy={buy_xy}）")
        return 1
    log(t0, f"Phase3: 票价 {price_xy}，确定按钮 {buy_xy}（单 dump）")

    # Phase 4：shell 连点 [票价, 确定, 确定]
    confirmed = up.shell_price_and_buy_until_confirm(price_xy, buy_xy, t0)
    path = "shell批量连点"
    if not confirmed:
        log(t0, "Phase4 shell 路未确认，回退元素点击")
        if up.element_click_price() and up.element_click_buy():
            poll_end = time.monotonic() + 0.55   # 上游 _wait_for_confirm_ready(0.55)
            while time.monotonic() < poll_end:
                if up.confirm_page_ready():
                    confirmed = True
                    break
                time.sleep(0.02)
        path = "元素点击回退"
    if not confirmed:
        log(t0, "STOP: 确认页未出现（连点+元素回退均超时）")
        return 1
    log(t0, f"Phase4: 到达订单确认页（{path}）")

    # 收尾：观演人 checkbox，停提交前
    n_box, fb = up.finish_confirm(t0)
    root = up.dump_xml()
    (out / "s3_order.xml").write_bytes(ET.tostring(root))
    checked = sum(1 for n in root.iter("node")
                  if n.get("resource-id", "") == CHECKBOX and n.get("checked") == "true")
    submit_ok = any((n.get("text") or "") == "立即提交" for n in root.iter("node"))
    # 总额匹配：抓「¥ 780.00」样式的订单总额（避开花呗分期「¥265.98 x 3期」）
    page_text = "\n".join((n.get("text") or "") for n in root.iter("node"))
    totals = re.findall(r"¥\s*([\d,]+\.\d{2})", page_text)
    amount_match = any(
        abs(float(t.replace(",", "")) - expected_total) < 0.01
        for t in totals
    )
    log(t0, f"订单核对: checkbox 已选 {checked}/{n_box}，提交按钮可见={submit_ok}，"
            f"总额匹配({args.expected_total})={amount_match}，全文金额={totals}")
    if checked < n_box or not amount_match:
        log(t0, "RESULT: ⚠️ 到达订单页但勾选/金额未达标——停机交人工（未提交）")
        return 1
    log(t0, "RESULT: ✅ 上游方法端到端（无提交）完成——停在『立即提交』前")
    return 0


if __name__ == "__main__":
    sys.exit(main())
