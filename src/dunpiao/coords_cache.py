# -*- coding: utf-8 -*-
"""跨次运行的坐标缓存——上游 fast_pipeline 坐标缓存的持久化版。

上游 fast_pipeline 的 warm 运行把 CTA/票价/确定按钮坐标缓存在进程内存
（_cached_coords / _put_hot_coord，_WARM_REQUIRED_KEYS：detail_buy、price、
sku_buy）；本 runner 每次是独立进程，故落盘到 logs/coords_cache.json
（gitignored，含敏感设备信息一律不入库）：

    { "<cache_key>": {"cta_xy": [x, y], "price_xy": [x, y], "buy_xy": [x, y],
                      "screen": [w, h], "price_index": N, "saved_at": "..."} }

预填时机：预约态即可进 SKU 页测量——开票只改 CTA 容器内的文案/像素，
不改容器位置；场次与票档数不变则 SKU 页坐标不变。开票前跑一次
`--capture-coords` 预存，开票 T0 即可用缓存坐标直点，热路径跳过两次 dump。

信任分层（照上游 formal/rush 的分层信任，缓存只存坐标不存决策）：
  - 复用前廉价校验（不 dump）：屏尺寸一致、price_index 一致、三点在屏内、
    activity 是详情页、入口轮询确认 SKU 页
  - 缓存点错自愈：确认页未出现 → 重新 dump 重测一次 → 仍失败走元素点击
    回退 → 全失败 STOP（绝不盲点到底）
  - 决策安全网不变：选档正确性由订单核对（金额/张数/观演人/实勾数）兜底
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path


def cache_path(root: Path) -> Path:
    return root / "logs" / "coords_cache.json"


def load(root: Path, key: str) -> dict | None:
    p = cache_path(root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    c = data.get(key) if isinstance(data, dict) else None
    return c if isinstance(c, dict) else None


def save(root: Path, key: str, entry: dict) -> None:
    p = cache_path(root)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    entry = dict(entry)
    entry["saved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    data[key] = entry
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
