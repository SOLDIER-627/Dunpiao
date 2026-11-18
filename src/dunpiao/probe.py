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


def analyze(root: ET.Element, package: str) -> dict:
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
            "button_ready": False,        # 按钮级就绪（id 或 词表命中）
            "button_text": None,
            "button_via_desc": False,
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
            "CTA 容器存在但为空：购票栏未渲染（预约未开票或页面未加载完）；"
            "上游原版在此场景判 ready=true（容器级），本探针判未就绪"
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
    package = d.app_current().get("package", "")
    xml = d.dump_hierarchy()
    if save_xml:
        Path(save_xml).write_text(xml, encoding="utf-8")
    root = ET.fromstring(xml)
    report = analyze(root, package)
    report["meta"] = {
        "probe": "dunpiao-probe-v1",
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "xml_bytes": len(xml),
        "read_only": True,
    }
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
