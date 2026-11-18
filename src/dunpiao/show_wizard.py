"""新演出信息 AI 化确认向导（旁路任务，对应 E2E-01 的前置工具）。

两种模式，把"确认"这一层交给 AI 助手完成：

1. capture（只读）：手机停在目标演出详情页，dump 一次，输出结构化
   演出信息 JSON（标题/场馆/当前场次/价格区间/票档在售状态）。
   AI 助手拿这份 JSON 在对话中向用户逐项展示并确认——替代人工肉眼核对。

2. apply（写配置）：AI 助手把用户确认的结果作为参数传入，只覆盖
   config.local.jsonc 的目标演出字段（keyword/date/price/target_title/
   target_venue），**绝不触碰 users（观演人）等敏感字段**；同时把完整
   档案写入 logs/shows/<tag>.json（gitignored）。

设计约束（E2E-01，逐条对应调研结论）：
- 预检档案只存信息，不存坐标——坐标一律运行时重新定位（开票后布局会变）
- 多场次演出：在手机上切换场次后必须重新 capture 重采票档
  （实测踩坑：不同场次票档数与在售状态不同）
- capture 全程零点击；apply 只写本地文件，不碰设备

用法：
    .venv/bin/python -m src.dunpiao.show_wizard capture [--serial S]
    .venv/bin/python -m src.dunpiao.show_wizard apply --tag X \
        --keyword 李大奔 --date "11月28日 周六" --price 380 \
        [--title ... --venue ...] [--price-index 4] [--capture FILE]

退出码：capture 成功 0；不在详情页 2；apply 成功 0。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.dunpiao import probe  # noqa: E402

PRICE_CONTAINER_SUFFIX = "project_detail_perform_price_flowlayout"
SHOWS_DIR = ROOT / "logs" / "shows"
CONFIG_PATH = ROOT / "config.local.jsonc"

# apply 允许覆盖的字段白名单——白名单之外一律拒绝（观演人信息永不出手）
APPLY_FIELDS = ("keyword", "date", "price", "price_index", "target_title", "target_venue")


def parse_bounds(s: str | None) -> list[int] | None:
    if not s or not s.startswith("["):
        return None
    m = re.findall(r"\d+", s)
    if len(m) != 4:
        return None
    return [int(v) for v in m]


def tier_candidates(root: ET.Element):
    """复制自 scripts/e2e_run.py（同源逻辑，注明出处；不 import 以免耦合）。

    在售票档 = 票价容器内无『缺货登记』标签的档（XML 层判别，实测结论）。
    返回 (全部档 bounds 列表, 在售档 bounds 列表)。
    """
    sold, tiers = set(), []
    for n in root.iter("node"):
        if (n.get("resource-id") or "").endswith(PRICE_CONTAINER_SUFFIX):
            for tier in n:
                tb = parse_bounds(tier.get("bounds"))
                tiers.append(tb)
                if any(
                    (t.get("text") or "").strip() == "缺货登记" for t in tier.iter("node")
                ):
                    sold.add(tuple(tb))
    all_tiers = [b for b in tiers if b]
    return all_tiers, [b for b in all_tiers if tuple(b) not in sold]


def connect(serial: str | None):
    import uiautomator2 as u2

    d = u2.connect(serial)
    # 与 e2e_run 一致：关隐式等待，本脚本只读不点击
    d.settings["wait_timeout"] = 0
    d.settings["operation_delay"] = (0, 0)
    return d


def capture(serial: str | None = None) -> dict:
    """只读采集当前详情页演出信息。零点击。"""
    d = connect(serial)
    cur = d.app_current()
    activity = cur.get("activity", "")
    if "ProjectDetailActivity" not in activity:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"手机当前不在演出详情页（activity={activity.split('.')[-1]}）。"
                    "请先在大麦 App 打开目标演出详情页再采集。",
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)
    xml = d.dump_hierarchy()
    root = ET.fromstring(xml)
    rep = probe.analyze(root, "cn.damai", activity)
    all_tiers, avail = tier_candidates(root)
    info = {
        "ok": True,
        "captured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "title": rep.get("title"),
        "venue": rep.get("venue"),
        "show_time": rep.get("show_time"),
        "price_range": rep.get("price_range"),
        "presale_banner": rep.get("preset_banner", {}).get("text"),
        "tiers_total": len(all_tiers),
        "tiers_available": len(avail),
        "tier_bounds": all_tiers,
        "available_bounds": avail,
        "warnings": rep.get("warnings", []),
    }
    SHOWS_DIR.mkdir(parents=True, exist_ok=True)
    out = SHOWS_DIR / f"capture_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    info["capture_file"] = str(out.relative_to(ROOT))
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return info


def _replace_jsonc_value(text: str, key: str, value) -> str:
    """就地替换 config.local.jsonc 中某个键的值，保留全部注释与格式。

    匹配 "key": <old>；old 支持 "..."、数字、null、true/false。
    找不到该键则报错（宁可失败也不静默新增——配置语义必须人工可见）。
    """
    if isinstance(value, str):
        new = json.dumps(value, ensure_ascii=False)
    elif value is None:
        new = "null"
    else:
        new = json.dumps(value)
    pat = re.compile(r'("%s"\s*:\s*)("[^"]*"|[-\w.]+)' % re.escape(key))
    if not pat.search(text):
        raise SystemExit(f"STOP: config.local.jsonc 中找不到键 {key!r}，拒绝静默新增")
    return pat.sub(lambda m: m.group(1) + new, text, count=1)


def apply_config(args) -> int:
    """白名单字段写入 config.local.jsonc + 归档演出档案。不碰设备。"""
    values = {
        k: getattr(args, k) for k in APPLY_FIELDS if getattr(args, k, None) is not None
    }
    if not values:
        raise SystemExit("STOP: apply 至少要提供一个字段（--keyword/--date/--price/…）")

    text = CONFIG_PATH.read_text("utf-8")
    for k, v in values.items():
        text = _replace_jsonc_value(text, k, v)
    CONFIG_PATH.write_text(text, encoding="utf-8")
    print(f"config.local.jsonc 已更新：{', '.join(values)}")

    # 归档档案：合并最近的 capture（若未显式指定）
    SHOWS_DIR.mkdir(parents=True, exist_ok=True)
    cap_path = Path(args.capture) if args.capture else None
    if cap_path is None:
        caps = sorted(SHOWS_DIR.glob("capture_*.json"))
        cap_path = caps[-1] if caps else None
    profile = {
        "show_tag": args.tag,
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "config_overrides": values,
        "note": "档案只存信息不存坐标；多场次演出每个场次单独 capture 重采。",
    }
    if cap_path and cap_path.exists():
        profile["capture"] = json.loads(cap_path.read_text("utf-8"))
    out = SHOWS_DIR / f"{args.tag}.json"
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"演出档案已归档：{out.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("capture", help="只读采集当前详情页演出信息（零点击）")
    p1.add_argument("--serial", default=None)

    p2 = sub.add_parser("apply", help="把确认结果写入 config.local.jsonc 并归档")
    p2.add_argument("--tag", required=True, help="演出标识，如 libenben_780_20261128")
    p2.add_argument("--keyword")
    p2.add_argument("--date")
    p2.add_argument("--price")
    p2.add_argument("--price-index", type=int, dest="price_index")
    p2.add_argument("--title", dest="target_title")
    p2.add_argument("--venue", dest="target_venue")
    p2.add_argument("--capture", help="指定 capture 文件（默认取最新）")
    args = ap.parse_args()

    t0 = time.perf_counter()
    if args.cmd == "capture":
        capture(args.serial)
    else:
        apply_config(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
