#!/usr/bin/env python
"""猫眼执行链路——与大麦 engine 同一套 5 阶段纪律，只换定位方式。

阶段（与 engine.py 一致）：
  s0 回到详情页   activity 判定 + BACK 阶梯
  s1 点购票 CTA   底部区域文案定位；阻断词（预约/已预约/未开售）默认拒绝点击
  s2 面板就绪     等待票档卡出现（可点击祖先 + ¥价格）
  s3 选档         按 --price-index 或 --price 文本点目标票档
  s4 确认按钮     底部区域找 确定/立即购买/下一步 类按钮
  s5 订单页核对   金额/张数/场次 + （--submit）提交；默认停在核对

纪律：默认**只读规划**（不点击）；--click 才点 CTA/票档/确认；--submit 才提交。
付款永远人工；验证码/风控出现即停。
"""
from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from src.dunpiao import maoyan as M
from src.dunpiao import runtime_lock

CONFIRM_TEXTS = ("确定", "确认", "立即购买", "立即购票", "下一步", "去支付", "立即预订", "立即预定")
ORDER_MARKERS = ("确认购买", "订单确认", "实名观演人", "立即提交", "支付方式", "配送方式")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def snap(d, tag, out_dir):
    xml = d.dump_hierarchy()
    (out_dir / f"{tag}.xml").write_text(xml, encoding="utf-8")
    return ET.fromstring(xml)


def tap(d, bounds, label):
    cx, cy = (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2
    d.shell(f"input tap {cx} {cy}")
    log(f"点击 {label} @({cx},{cy})")


def find_confirm(root):
    """底部区域（y>1900）找确认类按钮：可点击 + 文本命中 CONFIRM_TEXTS。"""
    best = None
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        b = M._bounds(n)
        if not b or b[1] < 1900:
            continue
        text = M._norm(M._subtree_text(n))
        if not text:
            continue
        hit = next((k for k in CONFIRM_TEXTS if k in text), None)
        if hit:
            best = {"text": M._subtree_text(n)[:40], "bounds": b, "hit": hit}
    return best


def order_like(root):
    blob = " ".join(M._text(n) for n in root.iter("node") if M._text(n))
    return next((m for m in ORDER_MARKERS if m in blob), None)


def run(args) -> int:
    """猫眼链路。args 需含: serial/price_index/price/expected_total/click/submit/
    allow_blocked_cta。由 scripts/rush.py 在检测到猫眼前台时调用。"""
    import uiautomator2 as u2
    lock = runtime_lock.DeviceInstanceLock(args.serial or "default")
    if not lock.acquire():
        log("STOP: 该设备已有另一个运行器在跑（单实例锁被占用）")
        return 1
    d = u2.connect(args.serial) if args.serial else u2.connect()
    d.settings["wait_timeout"] = 0
    out_dir = ROOT / "logs" / f"maoyan_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"=== 猫眼链路开始（click={'ON' if args.click else 'OFF'}，"
        f"submit={'ON' if args.submit else 'OFF'}，证据目录 {out_dir.name}）===")

    cur = d.app_current()
    if cur.get("package") != M.PACKAGE:
        log(f"STOP: 前台不是猫眼（{cur.get('package')}）——请打开猫眼目标演出页")
        return 1

    # ---- s0：确保在详情页（不在则 BACK）----
    root = snap(d, "s0", out_dir)
    r = M.extract(root, cur.get("activity", ""))
    for _ in range(3):
        if r["state"] == "detail_page":
            break
        log(f"s0: 当前 {r['state']}，BACK 返回详情页")
        d.shell("input keyevent 4")
        time.sleep(0.8)
        root = snap(d, "s0_back", out_dir)
        r = M.extract(root, d.app_current().get("activity", ""))
    if r["state"] != "detail_page":
        log(f"STOP: 未回到猫眼详情页（state={r['state']}）")
        return 1
    log(f"s0: 详情页 OK — {r['title']!r} / {r['show_time']!r} / {r['price_range']!r}")

    # ---- s1：CTA ----
    cta = r.get("cta")
    if not cta:
        log("STOP: 未找到底部购票 CTA")
        return 1
    log(f"s1: CTA {cta['text']!r} 可点={cta['safe_to_click']} 阻断词={cta['blocked_text']}")
    if not cta["safe_to_click"] and not args.allow_blocked_cta:
        log("STOP: CTA 处于预约/未开售态（阻断词命中）——默认不点击；"
            "模拟演练可加 --allow-blocked-cta")
        return 1
    if args.click:
        tap(d, cta["bounds"], "购票 CTA")
    else:
        log("（只读规划：不点击 CTA）")
        return 0

    # ---- s2：面板就绪（票档卡出现）----
    tiers = None
    deadline = time.monotonic() + 8.0
    last_state = None
    while time.monotonic() < deadline:
        root = snap(d, "s2", out_dir)
        rr = M.extract(root, d.app_current().get("activity", ""))
        if rr["state"] != last_state:
            last_state = rr["state"]
            log(f"s2: 轮询 state={rr['state']} tiers={len(rr.get('tiers') or [])}")
        tiers = rr.get("tiers")
        if tiers:
            break
        time.sleep(0.25)
    if not tiers:
        log("STOP: 面板未出现票档卡（可能仍在详情页或加载中）")
        return 1
    log(f"s2: 面板就绪，场次 {len(rr.get('sessions') or [])} 个，票档 {len(tiers)} 档")
    for t in tiers:
        log(f"     [{t['index']}] {t['name']!r:<14} ¥{t['price']:<6} {t['status']}")

    # ---- s3：选目标票档 ----
    target = None
    if args.price:
        target = next((t for t in tiers if t["price"] == str(args.price)), None)
    elif args.price_index is not None:
        target = next((t for t in tiers if t["index"] == args.price_index), None)
    if target is None:
        log(f"STOP: 未匹配到目标票档（price={args.price} price_index={args.price_index}）")
        return 1
    log(f"s3: 目标 [{target['index']}] {target['name']!r} ¥{target['price']} {target['status']}")
    tap(d, target["bounds"], f"票档 ¥{target['price']}")
    time.sleep(0.6)
    root = snap(d, "s3_after_tier", out_dir)

    # ---- s4：确认按钮 ----
    conf = find_confirm(root)
    if conf:
        log(f"s4: 确认按钮 {conf['text']!r} 命中={conf['hit']!r} bounds={conf['bounds']}")
    else:
        log("s4: 底部未找到确认类按钮——当前面板可能仍处于预约态（预约态无确认按钮）")
        log("    底部区域文本：")
        for n in root.iter("node"):
            b = M._bounds(n)
            x = M._text(n)
            if x and b and b[1] > 2350:
                log(f"      {x!r} {b}")
        log("RESULT: 模拟到「选档完成」为止（预约态无确认按钮，符合预期）")
        return 0

    if args.click:
        tap(d, conf["bounds"], f"确认按钮 {conf['hit']}")
        time.sleep(1.0)

    # ---- s5：订单页核对 ----
    root = snap(d, "s5", out_dir)
    marker = order_like(root)
    if not marker:
        log("s5: 未进入订单页（无订单页标记）——交人工看屏幕")
        return 1
    log(f"s5: 进入订单页（标记 {marker!r}）")
    texts = [M._text(n) for n in root.iter("node") if M._text(n)]
    amount = next((x for x in texts if x.startswith("¥") or x.startswith("￥")), None)
    log(f"s5: 金额文本 {amount!r}")
    if args.expected_total and amount:
        norm = amount.replace("¥", "").replace("￥", "").replace(",", "").strip()
        if norm != args.expected_total:
            log(f"STOP: 金额不符（页面 {norm} != 期望 {args.expected_total}）——不提交")
            return 1
        log(f"s5: 金额核对通过 {norm}")
    if not args.submit:
        log("RESULT: ✅ 到订单页且核对完成（未提交）——付款人工")
        return 0
    sub = next((n for n in root.iter("node")
                if M._text(n) in ("立即提交", "提交订单", "确认支付")), None)
    if not sub:
        log("STOP: 订单页未找到提交按钮——不提交")
        return 1
    log("s5: 点击提交（已授权 --submit）")
    tap(d, M._bounds(sub), "提交")
    time.sleep(2.0)
    root = snap(d, "s6_after_submit", out_dir)
    log(f"s6: 提交后 activity={d.app_current().get('activity')}（只读，不再点击）")
    return 0


