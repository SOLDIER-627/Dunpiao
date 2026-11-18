# -*- coding: utf-8 -*-
"""改版只读探针 v1（PH-04 初版交付物）。

对照基准：上游 HaTickets 76946bf 原版 --probe（2026-11-18 一次通过，
详见 docs/research/HaTickets基线固定_2026-11-18.md）。

与上游的差异（本探针的改进点）：
  1. 区分"容器级就绪"与"按钮级就绪"——本机样本证实预约阶段 CTA 容器存在但为空，
     上游原版判 ready=true 属于容器级误报；
  2. CTA 命中同时查 text 与 content-desc（图片化 CTA 可能只有 desc）；
  3. 新增预选横幅（goto_setinfo）检测——对应"预选机制"热路径压缩情报；
  4. 纯 stdlib 解析 dump_hierarchy，不依赖上游代码；任何状态下零点击。

用法：
  .venv/bin/python -m src.dunpiao.probe [--serial SERIAL] [--json PATH]
  （手机需提前停在目标页面；本探针不做任何页面跳转）
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dunpiao import selectors as S  # noqa: E402


def _rid(node: ET.Element) -> str:
    return (node.get("resource-id") or "").strip()


def _text(node: ET.Element) -> str:
    return (node.get("text") or "").strip()


def _desc(node: ET.Element) -> str:
    return (node.get("content-desc") or "").strip()


def _find_by_ids(root: ET.Element, ids) -> list[ET.Element]:
    wanted = set(ids)
    return [n for n in root.iter("node") if _rid(n) in wanted]


def _visible(node: ET.Element) -> bool:
    return node.get("NAF") != "true"  # 粗判：非可交互但无内容的节点


def _first_text(root: ET.Element, ids) -> str | None:
    for n in _find_by_ids(root, ids):
        t = _text(n)
        if t:
            return t
    return None


def _text_marker_present(root: ET.Element, markers) -> str | None:
    for n in root.iter("node"):
        t = _text(n)
        if t and any(m in t for m in markers):
            return t
    return None


def _ids_with_text(root: ET.Element, ids) -> dict[str, str]:
    return {i: _text(n) for n in _find_by_ids(root, ids) if (i := _rid(n).split("/")[-1]) and _text(n)}


def _parse_bounds(s: str | None) -> list[int] | None:
    """'[x1,y1][x2,y2]' -> [x1,y1,x2,y2]。"""
    if not s:
        return None
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", s)
    return [int(g) for g in m.groups()] if m else None


def _looks_like_button(mean_rgb: tuple[float, float, float]) -> bool:
    """大麦购票按钮主色为橙红系：可购态 ≈ (235,116,59)，置灰/缺货态 ≈ (241,176,132)。
    粗判定，仅作辅助证据。"""
    r, g, b = mean_rgb
    return r > 170 and b < 160 and (r - b) > 70


def _button_appearance(mean_rgb: tuple[float, float, float]) -> str:
    """保守区分已见过的亮橙/浅橙样本；颜色仅是视觉线索。"""
    r, g, b = mean_rgb
    saturation = (max(mean_rgb) - min(mean_rgb)) / max(mean_rgb) if max(mean_rgb) else 0
    if 200 <= r <= 255 and 75 <= g < 155 and b < 115 and saturation >= 0.6:
        return "bright_orange"
    if 200 <= r <= 255 and 155 <= g <= 205 and 100 <= b <= 165:
        return "muted_orange"
    return "unknown"


def pixel_check_cta(screenshot, bounds: list[int] | None) -> dict | None:
    """对容器区域做像素验证：无障碍树不可见时判断按钮是否视觉存在。

    背景：本机实测大麦 9.0.38.6 购票 CTA 渲染在 BricksChannelPageActivity
    动态模板层，dump_hierarchy 与 u2 选择器均不可见，但按钮实际显示在容器
    bounds 内（橙色）。坐标点击仍可命中——与上游容器锚定做法兼容。
    """
    if not bounds:
        return None
    x1, y1, x2, y2 = bounds
    crop = screenshot.crop((x1, y1, x2, y2))
    px = list(crop.convert("RGB").getdata())
    if not px:
        return None
    n = len(px)
    mean = (sum(p[0] for p in px) / n, sum(p[1] for p in px) / n, sum(p[2] for p in px) / n)
    appearance = _button_appearance(mean)
    return {
        "button_visually_rendered": _looks_like_button(mean),
        "appearance_hint": appearance,
        "likely_active": appearance == "bright_orange",
        "mean_rgb": [round(v) for v in mean],
        "method": "container-region mean-color heuristic; not proof of clickability",
    }


def analyze(root: ET.Element, package: str, activity: str | None = None) -> dict:
    """从 UI 层级 XML 判定页面状态。纯函数，无副作用。"""
    report: dict = {
        "state": "unknown",
        "package": package,
        "title": None,
        "venue": None,
        "show_time": None,
        "price_range": None,
        "cta": {
            "container_present": False,
            "container_empty": None,      # 容器存在但无子节点 = True
            "container_bounds": None,     # 容器屏幕坐标 [x1,y1,x2,y2]
            "button_ready": False,        # 按钮级就绪（id 或 词表命中）
            "button_text": None,
            "button_via_desc": False,
            "button_visually_rendered": None,  # 像素验证：无障碍树不可见但视觉存在
            "appearance_hint": None,  # 亮橙/浅橙/未知，仅供保守判断
            "likely_active": None,  # 亮橙样本线索，不等于真实可点击状态
            "blocked_text": None,         # 售罄/未开售等阻断词
        },
        "preset_banner": {"present": False, "text": None},   # 预选入口
        "reservation_marker": None,
        "login_prompt": None,
        "sold_out_marker": None,
        "selectors_hit": {},
        "warnings": [],
    }

    # 登录拦截优先
    if login := _text_marker_present(root, S.LOGIN_PROMPT_MARKERS):
        report["login_prompt"] = login
        report["state"] = "login_blocked"
        return report

    # 订单确认页识别：类名（DmOrderActivity）或结构性标记。
    # 注意：详情页 activity 路径含 newtradeorder，不能裸匹配 "order" [L 实训踩坑]。
    cls = (activity or "").rsplit(".", 1)[-1].lower()
    is_order = cls.startswith("dmorder") or bool(
        _text_marker_present(root, ("确认购买", "实名观演人"))
    )
    if is_order:
        report["state"] = "order_confirm_page"
        order: dict = {"submit_button": None, "quantity_text": None, "total_price_text": None}
        for n in root.iter("node"):
            t = _text(n)
            if t == "立即提交" and n.get("clickable") == "true":
                order["submit_button"] = {
                    "bounds": _parse_bounds(n.get("bounds")),
                    "clickable": True,
                }
            elif re.fullmatch(r"×\d+张", t):
                order["quantity_text"] = t
            elif re.fullmatch(r"¥\s*[\d.]+", t):
                order["total_price_text"] = t
        report["order"] = order
        # 提交按钮可见 = 本页即提交闸门所在，警告必须带上
        if order["submit_button"]:
            report["warnings"].append(
                "订单确认页：提交按钮可见且可点击，本页为最终提交闸门；"
                "自动化到此必须停住交人工确认，绝不自动点击提交"
            )
        return report

    # SKU 页识别：活动名或票档容器结构（场次选择器缺失的售罄态也能识别）
    is_sku = bool(activity and "sku" in activity.lower()) or bool(
        _find_by_ids(root, S.PRICE_PANEL_CONTAINER_IDS)
    )
    if is_sku:
        report["state"] = "sku_page"
        # 票档条目：容器内 clickable 无名 FrameLayout（价格文本本版本完全不在无障碍树）
        tiers = []
        sold_out_tags = 0
        for n in root.iter("node"):
            if (n.get("resource-id") or "").endswith("project_detail_perform_price_flowlayout"):
                for child in n:
                    if child.get("clickable") == "true":
                        tiers.append(child.get("bounds"))
                for t in n.iter("node"):
                    txt = _text(t)
                    if txt and txt in S.PRICE_SOLD_OUT_TEXTS:
                        sold_out_tags += 1
                break
        report["sku"] = {
            "tier_count": len(tiers),
            "tier_bounds": tiers,
            "sold_out_tags": sold_out_tags,
            "all_sold_out": len(tiers) > 0 and sold_out_tags >= len(tiers),
        }
        if report["sku"]["all_sold_out"]:
            report["state"] = "sku_page_sold_out"
            report["sold_out_marker"] = "缺货登记"
        # SKU 确定按钮：同详情 CTA，无障碍不可见，bounds 锚定 + 像素验证
        for n in _find_by_ids(root, S.CTA_BUTTON_IDS):
            report["cta"]["container_present"] = True
            report["cta"]["container_empty"] = not _text(n) and not _desc(n) and len(list(n)) == 0
            report["cta"]["container_bounds"] = _parse_bounds(n.get("bounds"))
            report["cta"]["anchor"] = "btn_buy_view"
            break
        return report

    # 详情页判定：标题 ID 命中
    title = _first_text(root, S.TITLE_IDS)
    if not title:
        # 粗判其它页面（v1 只细分详情页，其余归 unknown 并记录线索）
        if _find_by_ids(root, S.SESSION_PICKER_IDS) or _text_marker_present(root, S.SESSION_PICKER_TEXTS):
            report["state"] = "sku_page"
        elif _text_marker_present(root, S.SUBMIT_TEXTS):
            report["state"] = "order_confirm_page"
        else:
            report["state"] = "unknown_or_other"
        return report

    report["state"] = "detail_page"
    report["title"] = title
    report["venue"] = _first_text(root, S.VENUE_IDS)
    report["show_time"] = _first_text(root, S.SHOW_TIME_IDS)

    # 价格区间（详情页头部）
    price_hits = _ids_with_text(root, S.PRICE_RANGE_IDS)
    if price_hits:
        pre = price_hits.get("project_price_pre", "")
        suffix = price_hits.get("project_price_suffix", "")
        char = price_hits.get("project_price_char", "¥")
        report["price_range"] = f"{char}{pre}-{suffix}" if pre and suffix else str(price_hits)

    # 选择器命中清单（调试/台账用）
    report["selectors_hit"] = {
        "title_ids": [i.split("/")[-1] for i in S.TITLE_IDS if _find_by_ids(root, (i,))],
        "price_layout": [i.split("/")[-1] for i in S.PRICE_LAYOUT_IDS if _find_by_ids(root, (i,))],
        "show_time": bool(_find_by_ids(root, S.SHOW_TIME_IDS)),
        "venue": bool(_find_by_ids(root, S.VENUE_IDS)),
    }

    # --- CTA：容器级 vs 按钮级 ---
    containers = _find_by_ids(root, (S.CTA_CONTAINER_ID,))
    if containers:
        report["cta"]["container_present"] = True
        report["cta"]["container_empty"] = len(list(containers[0])) == 0
        report["cta"]["container_bounds"] = _parse_bounds(containers[0].get("bounds"))

    button = None
    for n in _find_by_ids(root, S.CTA_BUTTON_IDS):
        if _text(n) or _desc(n):
            button = n
            break
    if button is None:
        # 词表兜底：全页找 text/desc 命中 CTA 词的可点击节点
        for n in root.iter("node"):
            blob = f"{_text(n)} {_desc(n)}"
            if n.get("clickable") == "true" and re.search(S.CTA_READY_PATTERN, blob):
                button = n
                break
    if button is not None:
        report["cta"]["button_ready"] = True
        report["cta"]["button_text"] = _text(button) or _desc(button)
        report["cta"]["button_via_desc"] = not _text(button) and bool(_desc(button))

    # 阻断词（售罄/未开售）——独立于按钮检测
    for n in root.iter("node"):
        blob = f"{_text(n)} {_desc(n)}"
        m = re.search(S.CTA_BLOCKED_PATTERN, blob)
        if m:
            report["cta"]["blocked_text"] = m.group(0)
            break

    # 预选横幅
    if _find_by_ids(root, S.PRESET_BANNER_IDS) or _text_marker_present(root, S.PRESET_BANNER_TEXTS):
        report["preset_banner"]["present"] = True
        report["preset_banner"]["text"] = _first_text(root, S.PRESET_BANNER_IDS) or "去设置"

    # 预约/售罄标记
    report["reservation_marker"] = _text_marker_present(root, S.RESERVATION_TEXT_MARKERS)
    report["sold_out_marker"] = _text_marker_present(root, S.PRICE_SOLD_OUT_TEXTS)

    # 状态细分与警告
    if report["cta"]["container_empty"] and not report["cta"]["button_ready"]:
        report["warnings"].append(
            "CTA 容器在无障碍树中为空：购票按钮可能渲染在动态模板层（Bricks），"
            "dump/选择器不可见；已用像素验证判定视觉存在性（button_visually_rendered）。"
            "坐标锚定点击仍有效（上游做法）；避免依赖无障碍树找购票按钮"
        )
    if report["preset_banner"]["present"]:
        report["warnings"].append(
            "检测到预选入口（去设置）：预约阶段建议由用户人工完成预选，"
            "热路径可压缩为 CTA→确定→提交 3 步"
        )
    return report


def run(serial: str | None = None, save_xml: str | None = None) -> dict:
    import uiautomator2 as u2

    d = u2.connect(serial) if serial else u2.connect()
    cur = d.app_current()
    package = cur.get("package", "")
    activity = cur.get("activity", "")
    xml = d.dump_hierarchy()
    if save_xml:
        Path(save_xml).write_text(xml, encoding="utf-8")
    root = ET.fromstring(xml)
    report = analyze(root, package, activity)
    report["meta"] = {
        "probe": "dunpiao-probe-v1",
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "xml_bytes": len(xml),
        "read_only": True,
        "activity": activity,
    }
    # 像素验证：锚点在但无障碍树看不到按钮时，截图判定按钮是否视觉存在
    cta = report["cta"]
    if cta["container_present"] and cta.get("container_bounds"):
        try:
            shot = d.screenshot()
            cta.update(pixel_check_cta(shot, cta["container_bounds"]) or {})
        except Exception as e:  # 像素验证失败不影响探针主流程
            report["warnings"].append(f"像素验证失败：{type(e).__name__}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="改版只读探针：判定大麦页面状态，零点击")
    ap.add_argument("--serial", default=None, help="设备序列号（单台可省略）")
    ap.add_argument("--json", default=None, help="JSON 报告输出路径（默认仅 stdout）")
    ap.add_argument("--save-xml", default=None, help="同时保存 UI 层级 XML 到指定路径")
    args = ap.parse_args()

    report = run(args.serial, save_xml=args.save_xml)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 退出码语义：detail_page=0，其余=1（供脚本判别）
    return 0 if report["state"] == "detail_page" else 1


if __name__ == "__main__":
    raise SystemExit(main())
