"""猫眼演出票适配层（只读提取）。

与大麦的差异（2026-11-18 真机实测，猫眼 com.sankuai.movie / MRNMovieActivity）：
- **内容节点没有 resource-id**（美团 RN 自绘）→ 只能靠文本 + bounds + 结构定位
- 详情页与场次/票档面板都在同一个 Activity（弹层），activity 名不区分
- 票档卡 = 可点击 ViewGroup，子树文本形如「看台 | ¥288 | 可预约」
- 场次卡 = 可点击 ViewGroup，子树文本形如「2026-12-05 周六 19:00 | 可预约」
- 预约态底部提示「开抢后有票会自动为您勾选」（猫眼自己会勾，比大麦省一步）

本模块只做**只读提取**（一次 dump + 纯解析），不点击、不下单。
猫眼的完整购票链路尚未接入 engine（engine 仍是按大麦资源 ID 写的），
见 docs/回流模式.md「平台差异」。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime

PACKAGE = "com.sankuai.movie"

# 购票 CTA 文案（可点击安全态）
CTA_SAFE_TEXTS = ("立即购票", "立即购买", "特惠购票", "选座购买", "立即预订", "立即预定", "购票")
# 不可点（预约/未开售/售罄）——出现即视为未开售或不可购
CTA_BLOCKED_TEXTS = (
    "已预约", "预约", "即将开抢", "待开售", "未开售", "开抢提醒", "缺货登记", "已售罄", "暂时无票",
)

# 票档不可购
UNAVAILABLE_TEXTS = ("缺货登记", "已售罄", "售罄", "无票", "暂时无票", "不可选", "暂不可售")
# 预约态
RESERVATION_TEXTS = ("可预约", "已预约", "预约", "即将开抢", "待开售", "开抢提醒")

_DATE_RE = re.compile(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}")
_WEEK_RE = re.compile(r"周[一二三四五六日天]")
_PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
_RANGE_RE = re.compile(r"^(\d+)\s*[-~]\s*(\d+)$")
_VENUE_RE = re.compile(r"(体育场|足球场|体育馆|剧场|剧院|演艺中心|文化中心|艺术中心|会展中心|中心)$")


def _text(n) -> str:
    return (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()


def _bounds(n):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
    return [int(x) for x in m.groups()] if m else None


def _center(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def _subtree_text(n) -> str:
    return " | ".join(x for x in (_text(d) for d in n.iter("node")) if x)


def _norm(s: str) -> str:
    """去空白后比较（猫眼常用「已 预 约」这种字间距排版）。"""
    return re.sub(r"\s+", "", s or "")


def _parent_map(root):
    return {c: p for p in root.iter() for c in p}


def _nearest_clickable(node, parents):
    """自下而上找最近的可点击祖先（上游 _find_clickable_ancestor 同款）。"""
    cur = node
    while cur is not None:
        if cur.get("clickable") == "true" and _bounds(cur):
            return cur
        cur = parents.get(cur)
    return None


def _texts_with_bounds(root):
    out = []
    for n in root.iter("node"):
        x = _text(n)
        if x and n.get("visible-to-user") != "false":
            b = _bounds(n)
            if b:
                out.append((x, b, n))
    return out


def _clickables(root):
    """可点击节点 + 子树文本 + bounds（猫眼没有 resource-id，全靠这个）。"""
    out = []
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        b = _bounds(n)
        if not b:
            continue
        out.append({"node": n, "bounds": b, "text": _subtree_text(n)})
    return out


def extract_tiers(root):
    """票档列表：含 ¥价格的文本节点 → 最近可点击祖先 = 一张票卡。

    返回 [{"index", "name", "price", "status", "bounds"}]；非面板页返回 None。
    """
    parents = _parent_map(root)
    seen = {}
    for n in root.iter("node"):
        price_text = _text(n)
        m = _PRICE_RE.search(price_text)
        if not m or n.get("visible-to-user") == "false":
            continue
        card = _nearest_clickable(n, parents)
        if card is None:
            continue
        key = tuple(_bounds(card))
        if key in seen:
            continue
        blob = _subtree_text(card)
        texts = [x for x in blob.split(" | ") if x]
        name = next((t for t in texts if not _PRICE_RE.search(t) and not any(
            k in _norm(t) for k in UNAVAILABLE_TEXTS + RESERVATION_TEXTS)), "")
        status = "available"
        if any(k in _norm(blob) for k in UNAVAILABLE_TEXTS):
            status = "sold_out"
        elif any(k in _norm(blob) for k in RESERVATION_TEXTS):
            status = "reservation"
        seen[key] = {
            "index": len(seen),
            "name": name,
            "price": m.group(1),
            "status": status,
            "bounds": list(key),
            "texts": texts,
        }
    return list(seen.values()) or None


def extract_sessions(root):
    """场次列表：含「日期 + 周X」的文本节点 → 最近可点击祖先 = 场次卡。"""
    parents = _parent_map(root)
    seen = {}
    for n in root.iter("node"):
        x = _text(n)
        if not (_DATE_RE.search(x) and _WEEK_RE.search(x)):
            continue
        if n.get("visible-to-user") == "false":
            continue
        card = _nearest_clickable(n, parents)
        if card is None:
            continue
        key = tuple(_bounds(card))
        if key in seen:
            continue
        blob = _subtree_text(card)
        texts = [t for t in blob.split(" | ") if t]
        seen[key] = {
            "index": len(seen),
            "date": next((t for t in texts if _DATE_RE.search(t)), ""),
            "status": "reservation" if any(k in _norm(blob) for k in RESERVATION_TEXTS) else "available",
            "bounds": list(key),
            "texts": texts,
        }
    return list(seen.values()) or None


def extract_cta(root):
    """底部购票 CTA：屏幕下 1/4 区域内、文本命中购票/预约词的可点击节点。"""
    cands = []
    for c in _clickables(root):
        if c["bounds"][1] < 1900:
            continue
        text = _norm(c["text"])
        if not text:
            continue
        blocked = next((k for k in CTA_BLOCKED_TEXTS if k in text), None)
        safe = next((k for k in CTA_SAFE_TEXTS if k in text), None)
        if blocked or safe:
            cands.append({
                "text": c["text"][:60],
                "bounds": c["bounds"],
                "center": _center(c["bounds"]),
                "safe_to_click": bool(safe) and not blocked,
                "blocked_text": blocked,
            })
    return cands[-1] if cands else None


def extract(root, activity: str = "") -> dict:
    """猫眼页面只读提取（详情页 / 场次票档面板 通用）。"""
    texts = _texts_with_bounds(root)
    title = ""
    for x, b, _ in texts:
        if 250 <= b[1] <= 430 and len(x) >= 6 and not _DATE_RE.search(x):
            if len(x) > len(title):
                title = x
    show_time = next((x for x, b, _ in texts if _DATE_RE.search(x) and _WEEK_RE.search(x)), "")
    venue = next((x for x, _, _ in texts if _VENUE_RE.search(x)), "")
    price_range = ""
    for i, (x, b, _) in enumerate(texts):
        m = _RANGE_RE.match(x)
        if m and i > 0 and texts[i - 1][0].strip() in ("¥", "￥"):
            price_range = f"¥{m.group(1)}-{m.group(2)}"
            break
    if not price_range:
        for x, _, _ in texts:
            m = _RANGE_RE.match(x)
            if m:
                price_range = f"¥{m.group(1)}-{m.group(2)}"
                break
    tiers = extract_tiers(root)
    sessions = extract_sessions(root)
    cta = extract_cta(root)
    return {
        "meta": {
            "tool": "dunpiao-maoyan-v1",
            "platform": "maoyan",
            "package": PACKAGE,
            "time": datetime.now().isoformat(timespec="seconds"),
            "activity": activity,
            "read_only": True,
        },
        "state": (
            "sku_panel" if tiers else
            # 详情页可能已滚动（标题滚出屏幕）——有 CTA 也认作详情页
            "detail_page" if (title or cta) else
            "unknown_or_other"
        ),
        "title": title or None,
        "venue": venue or None,
        "show_time": show_time or None,
        "price_range": price_range or None,
        "cta": cta,
        "sessions": sessions,
        "tiers": tiers,
        "reservation": any(
            any(k in _norm(x) for k in RESERVATION_TEXTS) for x, _, _ in texts
        ),
        "warnings": [] if tiers else [
            "未检测到票档卡：猫眼票档在场次弹层里，需点开底部购票/预约按钮后才可见"
        ],
    }
