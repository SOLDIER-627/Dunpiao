#!/usr/bin/env python
"""演出信息提取（只读，零点击）：当前页面 → 结构化 JSON。

配套 skill：.agents/skills/show-info-extract/SKILL.md
用法：
  .venv/bin/python scripts/show_info.py                       # 当前页面
  .venv/bin/python scripts/show_info.py --save-xml pagesamples/xx.xml
  .venv/bin/python scripts/show_info.py --serial <serial>

输出：stdout 一段人读摘要 + 一个 JSON 块（供脚本/流水线消费）。
安全：本脚本只 dump 与解析，不发出任何点击；进入 SKU 面板的 CTA 点击
由调用方（人工或 skill 指引）显式完成。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dunpiao import probe  # noqa: E402
from src.dunpiao import maoyan  # noqa: E402
from src.dunpiao import selectors as S  # noqa: E402

FLOWLAYOUT = "cn.damai:id/project_detail_perform_price_flowlayout"
PERFORM_FLOWLAYOUT = "cn.damai:id/project_detail_perform_flowlayout"
UNAVAILABLE_PATTERN = re.compile(r"(无票|缺货|售罄|不可选|不可售|暂时不可售|暂时售罄)")
RESERVATION_PATTERN = re.compile(r"(可预约|预约|预售|即将开抢|待开售|未开售)")
WEEK_PATTERN = re.compile(r"(周[一二三四五六日天]|\d{1,2}\.\d{1,2}|\d{4}\.\d{1,2}\.\d{1,2})")


def _parse_bounds(s):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", s or "")
    return [int(x) for x in m.groups()] if m else None


def _text(n):
    return (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()


def extract_session_items(root):
    """场次项 bounds 列表（两级面板第一级）。

    实测（2026-11-18 F✦FOREVER）：场次项自绘，无障碍树无任何文本，
    只能给出 bounds；序号（0-based，从上到下）就是 --session-index。
    选中项视觉为橙色描边+橙字，需看截图确认。
    """
    for node in root.iter("node"):
        if (node.get("resource-id") or "") == PERFORM_FLOWLAYOUT:
            return [
                {"index": i, "bounds": _parse_bounds(c.get("bounds") or "")}
                for i, c in enumerate(
                    c for c in node if c.get("clickable") == "true"
                )
            ]
    return []


def extract_tiers(root):
    """SKU 票档列表：index/bounds/文本/状态判定。"""
    for node in root.iter("node"):
        if (node.get("resource-id") or "") == FLOWLAYOUT:
            tiers = []
            for i, c in enumerate(node):
                if c.get("class") != "android.widget.FrameLayout" or c.get("clickable") != "true":
                    continue
                texts = [t for t in (_text(k) for k in c.iter("node")) if t]
                status = "unknown_or_available"
                if any(UNAVAILABLE_PATTERN.search(t) for t in texts):
                    status = "sold_out"
                elif any(RESERVATION_PATTERN.search(t) for t in texts):
                    status = "reservation"
                tiers.append({
                    "index": i,
                    "bounds": _parse_bounds(c.get("bounds") or ""),
                    "texts": texts,
                    "status": status,
                })
            return tiers
    return None


def extract_sessions(root):
    """场次线索：全页含 周X/日期 的可见文本（详情页与 SKU 面板通用）。"""
    out = []
    for n in root.iter("node"):
        if n.get("visible-to-user") == "false":
            continue
        t = _text(n)
        if t and WEEK_PATTERN.search(t) and len(t) <= 40:
            out.append({"text": t, "bounds": _parse_bounds(n.get("bounds") or "")})
    return out


def extract(root, activity):
    report = probe.analyze(root, "cn.damai", activity)
    visible_texts = [
        _text(n) for n in root.iter("node")
        if n.get("visible-to-user") != "false" and _text(n)
    ]
    return {
        "meta": {
            "tool": "dunpiao-show-info-v1",
            "time": datetime.now().isoformat(timespec="seconds"),
            "activity": activity,
            "read_only": True,
        },
        "state": report["state"],
        "title": report.get("title"),
        "venue": report.get("venue"),
        "show_time": report.get("show_time"),
        "price_range": report.get("price_range"),
        "reservation_marker": report.get("reservation_marker"),
        "sold_out_marker": report.get("sold_out_marker"),
        "cta": {
            "container_present": report["cta"].get("container_present"),
            "container_bounds": report["cta"].get("container_bounds"),
            "button_ready": report["cta"].get("button_ready"),
            "button_text": report["cta"].get("button_text"),
            "blocked_text": report["cta"].get("blocked_text"),
            "likely_active": report["cta"].get("likely_active"),
        },
        "sku_tiers": extract_tiers(root),
        "session_items": extract_session_items(root),
        "session_candidates": extract_sessions(root),
        "preset_banner": report.get("preset_banner"),
        "visible_texts_head": visible_texts[:60],
        "warnings": report.get("warnings", []),
    }


def human(r):
    lines = []
    plat = r.get("meta", {}).get("platform", "damai")
    lines.append(
        f"页面状态 : {r['state']}  （{plat}，activity={r['meta']['activity'].rsplit('.', 1)[-1]}）"
    )
    if r.get("title"):
        lines.append(f"演出     : {r['title']}")
    if r.get("venue"):
        lines.append(f"场馆     : {r['venue']}")
    if r.get("show_time"):
        lines.append(f"演出时间 : {r['show_time']}")
    if r.get("price_range"):
        lines.append(f"价格区间 : {r['price_range']}")
    cta = r.get("cta") or {}
    if cta:
        if "safe_to_click" in cta:  # 猫眼格式
            lines.append(
                f"购票 CTA : {cta.get('text')!r} 可点={cta.get('safe_to_click')} "
                f"阻断词={cta.get('blocked_text') or '—'} 中心={cta.get('center')}"
            )
        else:
            lines.append(
                f"购票 CTA : 容器={'有' if cta.get('container_present') else '无'}"
                f" 按钮={'就绪' if cta.get('button_ready') else '不可见'}"
                f" 文本={cta.get('button_text') or '—'} 阻断词={cta.get('blocked_text') or '—'}"
                f" 亮橙={cta.get('likely_active')}"
            )
    # 猫眼：场次 + 票档
    if r.get("sessions"):
        lines.append("场次列表 :")
        for s in r["sessions"]:
            lines.append(f"  [{s['index']}] {s['status']:<12} {s['date']!r} bounds={s['bounds']}")
    if r.get("tiers"):
        lines.append("票档列表 :")
        for t in r["tiers"]:
            lines.append(
                f"  [{t['index']}] {t['status']:<18} {t.get('name','')!r:<14} "
                f"¥{t.get('price','')} bounds={t['bounds']}"
            )
    if r.get("session_items"):
        lines.append(
            "场次项   : " + " | ".join(
                f"[{s['index']}] {s['bounds']}" for s in r["session_items"]
            )
            + "  （自绘无文本，需截图确认选中项；序号即 --session-index）"
        )
    if r.get("sku_tiers") is not None and not r.get("tiers"):
        lines.append("票档列表 :")
        for t in r["sku_tiers"]:
            lines.append(
                f"  [{t['index']}] {t['status']:<18} bounds={t['bounds']} texts={t['texts']}"
            )
    if not r.get("tiers") and r.get("sku_tiers") is None:
        lines.append("票档列表 : （当前页无票档）")
    if r.get("session_candidates"):
        lines.append("场次线索 : " + " | ".join(c["text"] for c in r["session_candidates"][:10]))
    if r.get("reservation_marker"):
        lines.append(f"预约标记 : {r['reservation_marker']}")
    if r.get("sold_out_marker"):
        lines.append(f"售罄标记 : {r['sold_out_marker']}")
    for w in r.get("warnings", []):
        lines.append(f"⚠️ {w}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="大麦当前页演出信息提取（只读）")
    ap.add_argument("--serial", default=None)
    ap.add_argument("--save-xml", default=None, help="同时保存 dump XML")
    args = ap.parse_args()

    import uiautomator2 as u2
    d = u2.connect(args.serial) if args.serial else u2.connect()
    cur = d.app_current()
    package = cur.get("package", "")
    activity = cur.get("activity", "")
    xml = d.dump_hierarchy()
    if args.save_xml:
        Path(args.save_xml).write_text(xml, encoding="utf-8")
        print(f"XML 已存：{args.save_xml}", file=sys.stderr)
    root = ET.fromstring(xml)
    if package == maoyan.PACKAGE:
        r = maoyan.extract(root, activity)
    else:
        r = extract(root, activity)
        r["meta"]["platform"] = "damai" if package.startswith("cn.damai") else package
    print(human(r))
    print("\n```json")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
