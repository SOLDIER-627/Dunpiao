"""猫眼定位层（只换「怎么找元素」，流程与判定全部复用大麦 engine）。

猫眼（com.sankuai.movie / MRNMovieActivity）与大麦的唯一实质差异：
- 内容节点**没有 resource-id**（美团 RN 自绘）→ 用「文本 → 最近可点击祖先」
- 第一次点击后面板加载比大麦慢（实测 ~0.6-2s，大麦 0.15-0.3s）→ 入口等待放宽

本模块只提供定位函数，不做任何流程决策。
"""

from __future__ import annotations

import re

PACKAGE = "com.sankuai.movie"

# CTA 可点文案 / 阻断文案（预约、未开售、售罄）
CTA_SAFE_TEXTS = ("立即购票", "立即购买", "特惠购票", "选座购买", "立即预订", "立即预定", "购票")
CTA_BLOCKED_TEXTS = ("已预约", "预约", "即将开抢", "待开售", "未开售", "开抢提醒",
                     "缺货登记", "已售罄", "暂时无票")
# 票档不可购 / 预约态
UNAVAILABLE_TEXTS = ("缺货登记", "已售罄", "售罄", "无票", "暂时无票", "不可选", "暂不可售")
RESERVATION_TEXTS = ("可预约", "已预约", "预约", "即将开抢", "待开售", "开抢提醒")
# 确认类按钮文案（开售后才出现）
CONFIRM_TEXTS = ("确定", "确认", "立即购买", "立即购票", "下一步", "立即预订", "立即预定")
# 订单页标记（猫眼实测：确认购票 + 立即支付）
ORDER_MARKERS = ("确认购票", "确认购买", "订单确认", "实名观演人", "立即支付", "立即提交",
                 "支付方式", "取票方式", "配送方式")
# 提交按钮文案
SUBMIT_TEXTS = ("立即支付", "立即提交", "提交订单", "确认支付")

_DATE_RE = re.compile(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}")
_WEEK_RE = re.compile(r"周[一二三四五六日天]")
_PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
_RANGE_RE = re.compile(r"^(\d+)\s*[-~]\s*(\d+)$")
_VENUE_RE = re.compile(r"(体育场|足球场|体育馆|剧场|剧院|演艺中心|文化中心|艺术中心|会展中心|中心)$")


def text(n) -> str:
    return (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()


def norm(s: str) -> str:
    """去空白后比较（猫眼常带字间距：「已 预 约」）。"""
    return re.sub(r"\s+", "", s or "")


def bounds(n):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
    return [int(x) for x in m.groups()] if m else None


def center(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def subtree(n) -> str:
    return " | ".join(x for x in (text(d) for d in n.iter("node")) if x)


def _parents(root):
    return {c: p for p in root.iter() for c in p}


def _nearest_clickable(node, parents):
    cur = node
    while cur is not None:
        if cur.get("clickable") == "true" and bounds(cur):
            return cur
        cur = parents.get(cur)
    return None


def visible_texts(root):
    return [text(n) for n in root.iter("node")
            if n.get("visible-to-user") != "false" and text(n)]


def extract_cta(root):
    """底部购票 CTA（y>1900 的可点击节点，文本命中购票/预约词）。"""
    best = None
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        b = bounds(n)
        if not b or b[1] < 1900:
            continue
        blob = norm(subtree(n))
        if not blob:
            continue
        blocked = next((k for k in CTA_BLOCKED_TEXTS if k in blob), None)
        safe = next((k for k in CTA_SAFE_TEXTS if k in blob), None)
        if blocked or safe:
            best = {"text": subtree(n)[:40], "bounds": b, "center": center(b),
                    "safe_to_click": bool(safe) and not blocked, "blocked_text": blocked}
    return best


def extract_tiers(root):
    """票档卡：含 ¥价格 的文本节点 → 最近可点击祖先。返回 [{index,name,price,status,bounds}]。"""
    parents = _parents(root)
    seen = {}
    for n in root.iter("node"):
        m = _PRICE_RE.search(text(n))
        if not m or n.get("visible-to-user") == "false":
            continue
        card = _nearest_clickable(n, parents)
        if card is None:
            continue
        key = tuple(bounds(card))
        if key in seen:
            continue
        blob = subtree(card)
        parts = [x for x in blob.split(" | ") if x]
        name = next((x for x in parts if not _PRICE_RE.search(x) and not any(
            k in norm(x) for k in UNAVAILABLE_TEXTS + RESERVATION_TEXTS)), "")
        status = "available"
        if any(k in norm(blob) for k in UNAVAILABLE_TEXTS):
            status = "sold_out"
        elif any(k in norm(blob) for k in RESERVATION_TEXTS):
            status = "reservation"
        seen[key] = {"index": len(seen), "name": name, "price": m.group(1),
                     "status": status, "bounds": list(key)}
    return list(seen.values()) or None


def extract_sessions(root):
    """场次卡：含「日期 + 周X」的文本节点 → 最近可点击祖先。"""
    parents = _parents(root)
    seen = {}
    for n in root.iter("node"):
        x = text(n)
        if not (_DATE_RE.search(x) and _WEEK_RE.search(x)):
            continue
        if n.get("visible-to-user") == "false":
            continue
        card = _nearest_clickable(n, parents)
        if card is None:
            continue
        key = tuple(bounds(card))
        if key in seen:
            continue
        seen[key] = {"index": len(seen), "date": x, "bounds": list(key)}
    return list(seen.values()) or None


def extract_confirm(root):
    """底部确认类按钮（y>1900，文本命中 CONFIRM_TEXTS）。"""
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        b = bounds(n)
        if not b or b[1] < 1900:
            continue
        blob = norm(subtree(n))
        hit = next((k for k in CONFIRM_TEXTS if k in blob), None)
        if hit:
            return {"bounds": b, "center": center(b), "hit": hit, "text": subtree(n)[:30]}
    return None


def bottom_button(root):
    """底部大按钮（y>2450 且宽度>600）：预约态是「已预约」，开售后是购买按钮。"""
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        b = bounds(n)
        if not b or b[1] < 2450 or (b[2] - b[0]) < 600:
            continue
        return {"bounds": b, "center": center(b), "hit": None, "text": subtree(n)[:30]}
    return None


def parse_amount(root):
    """订单金额：猫眼把「¥」和数字拆成两个节点，需配对（大麦是单节点 ¥588.00）。"""
    texts = visible_texts(root)
    for i, x in enumerate(texts):
        if x.strip() in ("¥", "￥") and i + 1 < len(texts):
            nxt = texts[i + 1].strip()
            if re.fullmatch(r"\d+(?:\.\d{1,2})?", nxt):
                return nxt
    for x in texts:
        m = re.fullmatch(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)", x.strip())
        if m:
            return m.group(1)
    return None


def parse_tier_line(root):
    """票档行：「看台580元  ￥580 × 1张」→ (票档名, 单价, 数量)。"""
    for x in visible_texts(root):
        m = re.search(r"×\s*(\d+)\s*张", x)
        if m and ("¥" in x or "￥" in x):
            price = re.search(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)", x)
            name = re.sub(r"[¥￥].*$", "", x).strip()
            return {"name": name, "price": price.group(1) if price else None,
                    "qty": int(m.group(1))}
    return None


def find_submit(root):
    """提交按钮（立即支付/立即提交）。"""
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        blob = norm(subtree(n))
        hit = next((k for k in SUBMIT_TEXTS if k in blob), None)
        if hit:
            b = bounds(n)
            if b:
                return {"bounds": b, "center": center(b), "hit": hit}
    return None


def page_info(root):
    """页面概况（判定详情页/面板用）。"""
    texts = visible_texts(root)
    tiers = extract_tiers(root)
    cta = extract_cta(root)
    title = ""
    for n in root.iter("node"):
        x = text(n)
        b = bounds(n)
        if not (x and b and 150 <= b[1] <= 430 and len(x) >= 6):
            continue
        if _DATE_RE.search(x) or not re.search(r"[\u4e00-\u9fff]", x):
            continue  # 跳过日期行与资源名（如 order-gray-bg@2x）
        if len(x) > len(title):
            title = x
    show_time = next((x for x in texts if _DATE_RE.search(x) and _WEEK_RE.search(x)), "")
    venue = next((x for x in texts if _VENUE_RE.search(x)), "")
    price_range = ""
    for x in texts:
        m = _RANGE_RE.match(x)
        if m:
            price_range = f"¥{m.group(1)}-{m.group(2)}"
            break
    blob_all = " ".join(texts)
    if tiers:
        state = "sku_panel"
    elif any(k in blob_all for k in ORDER_MARKERS):
        state = "order_confirm"
    elif title or cta:
        state = "detail_page"
    else:
        state = "unknown_or_other"
    return {"state": state, "title": title or None, "venue": venue or None,
            "show_time": show_time or None, "price_range": price_range or None,
            "cta": cta, "tiers": tiers, "sessions": extract_sessions(root),
            "amount": parse_amount(root), "tier_line": parse_tier_line(root),
            "submit": find_submit(root), "blob": " ".join(texts)}
