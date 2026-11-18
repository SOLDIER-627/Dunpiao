"""回流票监听（P4）。

上游依据（逐字移植，不自造）：
- price_selector.py ``_PRICE_UNAVAILABLE_TAGS`` / ``_PRICE_UNAVAILABLE_PATTERN``：
  票档不可购状态词表与正则
- orchestrator.py ``_dismiss_fast_blocking_dialogs``：我知道了/下次再说/知道了/Cancel
  轻量阻塞弹窗的自动点掉（回流监听期间大麦会弹「已售罄…我知道了」）
- orchestrator.py ``run_with_retry``：外层轮次模型——可重试失败回监听，
  不可重试失败（验证码/待支付归属不了/结果未知）立即停
- orchestrator.py:2738：票档已售罄 → 停止本轮，回重试循环

回流场景与开售场景的差异：
- 无 T0、无 clock_sync——用监听循环替代倒计时，触发后走既有三击热路径
- 触发信号 = 目标票档区域不再含不可购词（文本层，本机实测缺货登记文本在
  无障碍树内）+ 确定按钮亮橙（像素层，辅助证据，不作为唯一依据）
- 大麦 SKU 页库存状态不自动刷新：缺货登记态会一直挂屏，监听循环必须
  周期性「BACK→详情页→CTA→重进 SKU」刷新库存（NNBS 回流监测同款要点）
- 二次回流：本轮提交后售罄 → 回监听继续蹲；结果未知/验证码 → 停机人工

安全边界：本模块只做**只读监听 + 弹窗点掉 + 页面刷新重进**，绝不触碰
提交边界；触发后由 e2e_run 既有闸门（核对→筛查→提交→只读验证）接管。
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

# ---- 上游 price_selector.py 词表（逐字）----
PRICE_UNAVAILABLE_TAGS = {
    "无票",
    "缺货",
    "缺货登记",
    "售罄",
    "已售罄",
    "不可选",
    "暂不可售",
}
PRICE_UNAVAILABLE_PATTERN = re.compile(
    r"(无票|缺货|售罄|不可选|不可售|暂(?:时)?不可售|暂(?:时)?售罄)"
)

# ---- 上游 orchestrator._dismiss_fast_blocking_dialogs 弹窗词（逐字）----
DISMISS_TEXTS = ("Cancel", "下次再说", "我知道了", "知道了")

FLOWLAYOUT = "cn.damai:id/project_detail_perform_price_flowlayout"
PERFORM_FLOWLAYOUT = "cn.damai:id/project_detail_perform_flowlayout"
SKU_ACTIVITY_KEYS = ("sku", "ncovsku")

# 日期解析（移植上游 date_utils._PATTERNS）
_DATE_PATTERNS = (
    re.compile(r"(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号]?"),
    re.compile(r"\d{4}[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})"),
    re.compile(r"(?P<m>\d{1,2})[./-](?P<d>\d{1,2})"),
)


# ---- 上游 event_navigator.py 场次面板资源（逐字）----
SESSION_PANEL_ID = "cn.damai:id/sku_panel_dates"
SESSION_DATE_ID = "cn.damai:id/tv_date"


def normalize_date(raw: str | None) -> str | None:
    """统一日期为 MM.DD（移植上游 date_utils.normalize_date）。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    for m in _DATE_PATTERNS:
        hit = m.search(raw)
        if not hit:
            continue
        try:
            month, day = int(hit.group("m")), int(hit.group("d"))
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month:02d}.{day:02d}"
    return None


def _build_parent_map(root):
    return {child: parent for parent in root.iter() for child in parent}


def enumerate_session_cards(root):
    """枚举场次卡片（移植上游 event_navigator._enumerate_sessions_from_xml）。

    上游靠 sku_panel_dates 面板 + tv_date 子节点拿日期文本；本机部分演出
    （qilin 座席版）**没有这两个 ID**，场次项自绘无文本——此时返回空列表，
    调用方回退到 session_item_bounds 的序号点选。
    """
    panel = None
    for node in root.iter("node"):
        if (node.get("resource-id") or "") == SESSION_PANEL_ID:
            panel = node
            break
    if panel is None:
        return []
    parent_map = _build_parent_map(root)
    cards = []
    for date_node in panel.iter("node"):
        if (date_node.get("resource-id") or "") != SESSION_DATE_ID:
            continue
        clickable = date_node
        cur = parent_map.get(date_node)
        while cur is not None:
            if cur.get("clickable") == "true":
                clickable = cur
                break
            cur = parent_map.get(cur)
        texts = [
            (d.get("text") or "").strip()
            for d in clickable.iter("node")
            if (d.get("text") or "").strip()
        ]
        cards.append({
            "index": len(cards),
            "date": (date_node.get("text") or "").strip(),
            "text": " ".join(texts),
            "bounds": clickable.get("bounds") or date_node.get("bounds"),
        })
    return cards


def pick_session_card(root, date=None, city=None, fallback_index=None):
    """按上游优先级选场次卡：date+city 唯一 → date 唯一 → fallback_index。

    返回 (card_dict, reason) 或 (None, reason)。
    """
    cards = enumerate_session_cards(root)
    if not cards:
        return None, "无日期文本场次卡（自绘面板，需 session_index）"
    target = normalize_date(date) if date else None
    if target:
        hits = [c for c in cards if normalize_date(c["date"]) == target]
        if city:
            narrowed = [c for c in hits if city in c["text"]]
            if len(narrowed) == 1:
                return narrowed[0], f"日期+城市唯一匹配 {target}/{city}"
            hits = narrowed or hits
        if len(hits) == 1:
            return hits[0], f"日期唯一匹配 {target}"
        if len(hits) > 1:
            return None, f"日期 {target} 命中 {len(hits)} 个场次（歧义）"
        return None, f"日期 {target} 未命中任何场次"
    if fallback_index is not None and 0 <= fallback_index < len(cards):
        return cards[fallback_index], f"序号回退 index={fallback_index}"
    return None, "无日期且无可用序号"


def _center(bounds):
    return ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)


def _parse_bounds(s):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", s or "")
    return [int(x) for x in m.groups()] if m else None


def _node_center_in(node_bounds, tier_bounds, slack=8):
    """节点中心是否落在票档 bounds 内（容差 slack px）。"""
    if not node_bounds:
        return False
    cx, cy = _center(node_bounds)
    x1, y1, x2, y2 = tier_bounds
    return (x1 - slack <= cx <= x2 + slack) and (y1 - slack <= cy <= y2 + slack)


def sku_tier_bounds(root, price_index: int):
    """取目标序号票档卡片 bounds（与 e2e_run.Runner.sku_coords 同款提取）。

    返回 [x1,y1,x2,y2] 或 None（容器缺失/序号越界）。
    """
    for node in root.iter("node"):
        if (node.get("resource-id") or "") == FLOWLAYOUT:
            cards = [
                c for c in node
                if c.get("class") == "android.widget.FrameLayout"
                and c.get("clickable") == "true"
            ]
            if 0 <= price_index < len(cards):
                return _parse_bounds(cards[price_index].get("bounds") or "")
            return None
    return None


def tier_is_unavailable(root, tier_bounds) -> bool | None:
    """目标票档区域是否处于不可购态（缺货登记等）。

    判定：票档 bounds 区域内文本命中上游不可购词表。返回：
    - True  = 不可购（缺货登记在屏）
    - False = 区域内无不可购词（可购候选）
    - None  = 无法判定（bounds 缺失）
    """
    if not tier_bounds:
        return None
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        if not text:
            continue
        if text in PRICE_UNAVAILABLE_TAGS or PRICE_UNAVAILABLE_PATTERN.search(text):
            if _node_center_in(_parse_bounds(node.get("bounds") or ""), tier_bounds):
                return True
    return False


def find_dismiss_coords(root):
    """找轻量阻塞弹窗按钮（我知道了/知道了/下次再说/Cancel）。

    上游 _dismiss_fast_blocking_dialogs 行为：命中即点掉。只点文本精确
    匹配的可点击节点，fail-closed（找不到返回 (None, None) 不点）。
    返回 (中心坐标, 弹窗文本)。
    """
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        if text in DISMISS_TEXTS and node.get("clickable") == "true":
            b = _parse_bounds(node.get("bounds") or "")
            if b:
                return _center(b), text
    return None, None


def _reenter_sku(d, log, cta_xy, max_backs=4):
    """BACK→详情页→CTA→重进 SKU（刷新库存）。成功返回 True。

    只用 activity 快查判定（零 dump），点击用 shell tap（HyperOS 实测
    无障碍点击不可靠）。
    """
    for _ in range(max_backs):
        act = d.app_current().get("activity", "")
        if any(k in act.lower() for k in SKU_ACTIVITY_KEYS):
            break
        if "projectdetail" in act.lower():
            break
        d.shell("input keyevent 4")
        time.sleep(0.5)
    else:
        return False
    act = d.app_current().get("activity", "")
    if "projectdetail" not in act.lower():
        # 已在 SKU 页：先 BACK 回详情页再重进
        d.shell("input keyevent 4")
        time.sleep(0.6)
        act = d.app_current().get("activity", "")
        if "projectdetail" not in act.lower():
            return False
    if cta_xy:
        d.shell(f"input tap {cta_xy[0]} {cta_xy[1]}")
        time.sleep(1.0)
    return any(k in d.app_current().get("activity", "").lower() for k in SKU_ACTIVITY_KEYS)


def session_item_bounds(root):
    """场次项 bounds 列表（两级面板第一级）。

    实测（2026-11-18 F✦FOREVER 上海场）：场次项自绘，无障碍树**无任何文本**
    （日期/周几均不可读），只能按 bounds 索引定位；索引顺序 = 面板从上到下。
    """
    for node in root.iter("node"):
        if (node.get("resource-id") or "") == PERFORM_FLOWLAYOUT:
            return [
                _parse_bounds(c.get("bounds") or "")
                for c in node if c.get("clickable") == "true"
            ]
    return []


def select_session(d, root, session_index: int, log=None, sleep=time.sleep, date=None,
                   city=None) -> bool:
    """点选目标场次：优先日期匹配（上游 event_navigator），否则按序号。"""
    card, reason = pick_session_card(root, date=date, city=city, fallback_index=session_index)
    if card is not None:
        b = _parse_bounds(card.get("bounds") or "")
        if b:
            xy = _center(b)
            d.shell(f"input tap {xy[0]} {xy[1]}")
            if log:
                log(f"reflow: 点选场次 {reason} @{xy}")
            sleep(1.2)
            return True
    items = session_item_bounds(root)
    if not items or session_index is None or session_index >= len(items):
        if log:
            log(f"reflow: 场次项不足（需要 index={session_index}，实际 {len(items)} 项）")
        return False
    xy = _center(items[session_index])
    d.shell(f"input tap {xy[0]} {xy[1]}")
    if log:
        log(f"reflow: 点选场次 index={session_index} @{xy}（自绘面板，无日期文本）")
    sleep(1.2)
    return True


def prepare_tiers(d, log, price_index: int, session_index: int | None = None,
                  sleep=time.sleep, wait: float = 2.5, poll: float = 0.25,
                  date=None, city=None):
    """确保面板已显示票档（两级面板：场次→票档）。

    实测（2026-11-18）：①面板刚打开时无障碍树**既无票档也无场次项**（动画/渲染
    未完成）——必须短等待重试，不能立即判死；②BACK 后重进 SKU 面板**不记得
    场次**，只显示场次列表——每次刷新后必须重选场次。
    返回 (root, tier_bounds)；tier_bounds 为 None 表示未能就绪。
    """
    deadline = time.monotonic() + wait
    root = None
    while True:
        try:
            root = ET.fromstring(d.dump_hierarchy())
        except Exception as e:
            log(f"reflow: dump 失败（{type(e).__name__}）")
            root = None
        else:
            tb = sku_tier_bounds(root, price_index)
            if tb is not None:
                return root, tb
            items = session_item_bounds(root)
            if items:
                if session_index is None:
                    log("reflow: 面板无票档且未给 session_index——无法进到票档层")
                    return root, None
                if not select_session(d, root, session_index, log, sleep=sleep,
                                      date=date, city=city):
                    return root, None
                try:
                    root = ET.fromstring(d.dump_hierarchy())
                except Exception:
                    return None, None
                return root, sku_tier_bounds(root, price_index)
        if time.monotonic() >= deadline:
            log("reflow: 面板未渲染（既无票档也无场次项）")
            return root, None
        sleep(poll)


def watch(
    d,
    log,
    *,
    price_index: int,
    cta_xy=None,
    session_index: int | None = None,
    interval: float = 2.0,
    refresh_every: float = 60.0,
    deadline_mono: float | None = None,
    max_ticks: int | None = None,
    require_texts: tuple = (),
    clock=time.monotonic,
    sleep=time.sleep,
) -> dict:
    """回流监听循环。返回 dict：

    - {"status": "ready", "tick": n, "tier_bounds": [...]}：目标票档可购，
      页面已在 SKU 且目标档无不可购词——调用方立即接管热路径
    - {"status": "timeout", "tick": n}：到 deadline/max_ticks 未回流

    每 tick：
    1. activity 快查：不在 SKU 页 → BACK/CTA 重进
    2. 周期性强制刷新（refresh_every，SKU 库存不自动刷新）
    3. dump → 轻弹窗（我知道了）点掉
    4. 护栏文本校验（require_texts，多场次同价位的防线）
    5. 目标票档不可购词判定：消失即触发
    """
    tick = 0
    last_refresh = clock()
    if deadline_mono is None:
        deadline_mono = float("inf")
    while clock() < deadline_mono:
        tick += 1
        if max_ticks is not None and tick > max_ticks:
            return {"status": "timeout", "tick": tick - 1}
        # 1) 位置守卫 + 2) 周期刷新（共用重进路径，重进即刷新库存）
        act = d.app_current().get("activity", "")
        on_sku = any(k in act.lower() for k in SKU_ACTIVITY_KEYS)
        stale = (clock() - last_refresh) >= refresh_every
        if not on_sku or stale:
            note = "周期刷新库存" if on_sku else "不在 SKU 页，重入"
            if not _reenter_sku(d, log, cta_xy):
                log(f"reflow: {note}失败——页面异常，下轮再试")
                sleep(interval)
                continue
            last_refresh = clock()
            log(f"reflow: {note}完成（tick={tick}）")
        # 3) 票档层就绪（两级面板：无票档时重选场次）+ 弹窗优先
        root, tb = prepare_tiers(
            d, log, price_index, session_index, sleep=sleep,
        )
        if root is None:
            sleep(interval)
            continue
        xy, dtext = find_dismiss_coords(root)
        if xy:
            d.shell(f"input tap {xy[0]} {xy[1]}")
            log(f"reflow: 点掉阻塞弹窗「{dtext}」（tick={tick}）")
            sleep(0.5)
            continue
        # 4) 护栏文本：多场次同价位时防误触发（重进面板可能落在其他场次）
        merged = " ".join(
            (n.get("text") or "").strip()
            for n in root.iter("node")
            if n.get("visible-to-user") != "false" and (n.get("text") or "").strip()
        )
        if require_texts and not all(t in merged for t in require_texts):
            log(f"reflow: 护栏文本缺失（需要 {list(require_texts)}，可能落在其他场次）——重进刷新")
            if _reenter_sku(d, log, cta_xy):
                last_refresh = clock()
            sleep(interval)
            continue
        # 5) 目标票档状态
        if tb is None:
            log(f"reflow: 票档容器缺失或序号越界（price_index={price_index}，tick={tick}）")
            sleep(interval)
            continue
        unavailable = tier_is_unavailable(root, tb)
        if unavailable is False:
            log(f"reflow: ✅ 目标票档可购信号（tick={tick}）——接管热路径")
            return {"status": "ready", "tick": tick, "tier_bounds": list(tb)}
        sleep(interval)
    return {"status": "timeout", "tick": tick}
