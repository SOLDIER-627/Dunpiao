# -*- coding: utf-8 -*-
"""瞬时错误（transient error）识别与自动恢复——上游机制移植。

对照基准：上游 HaTickets 76946bf
  - mobile/page_probe.py：TRANSIENT_ERROR_MARKERS / _RETRY_ACTION_TEXTS /
    _RETRY_ACTION_PHRASES / _nearest_retry_click_target /
    _is_local_transient_retry_pair / _find_local_transient_retry_coords
  - mobile/recovery.py：inspect_transient_failure / recover_transient_failure

上游核心纪律（全部保留）：
  1. 快路径只在同一层级里出现已知瞬时错误标记时，才点击一个「精确」的
     重试/刷新控件；验证码/人机验证永远不自动操作；
  2. 重试控件必须与错误标记「本地配对」（最近公共祖先在 1 条边内、且
     共同容器具备错误容器语义），配对不出就不点（fail-closed）；
  3. 点击用 shell input tap，结果未知时不做任何兜底点击（防重复点击）；
  4. 相同布局指纹的错误只处理一次（duplicate fingerprint 停手）。

本机观察补充（区别于上游）：2026-11-18 林忆莲场实战观察到「抢票人数太多，
请继续尝试」弹窗，按钮文案为「继续尝试」——不含上游词表里的「重试」二字，
故在本仓库词表追加 EXT_RETRY_ACTION_TEXTS（继续尝试/重新尝试/再试一次），
上游原词表保持不动。

纯 stdlib（xml.etree + hashlib），单设备 uiautomator2 直连。
"""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

# ---- 上游 mobile/page_probe.py 词表（逐字移植） ---------------------------

RETRY_ACTION_TEXTS = frozenset(
    {"重试", "重新加载", "重新刷新", "刷新", "点击重试"}
)
RETRY_ACTION_PHRASES = (
    "重新加载",
    "重新刷新",
    "点击重试",
    "点击重新加载",
    "请重试",
    "重试一下",
)
# 本机观察补充：继续尝试/重新尝试/再试一次（见模块 docstring）
EXT_RETRY_ACTION_TEXTS = frozenset(
    {"继续尝试", "重新尝试", "再试一次"}
)
# 本机观察补充：「抢票人数太多，请继续尝试」弹窗——上游错误词表只有
# 网络/加载类，不含人数类；追加后才能走同一套配对机制
EXT_TRANSIENT_ERROR_MARKERS = (
    "人数太多",
    "人数过多",
)
LOCAL_ERROR_CONTAINER_TOKENS = (
    "dialog",
    "empty",
    "error",
    "exception",
    "fail",
    "network",
    "reload",
    "retry",
)
TRANSIENT_ERROR_MARKERS = (
    "加载失败",
    "网络异常",
    "网络错误",
    "网络不给力",
    "网络开小差",
    "页面出错",
    "请求失败",
    "服务异常",
    "刷新失败",
    "连接失败",
    "暂无网络",
    "无网络连接",
)
# 全量错误标记 = 上游原词表 + 本机观察补充（人数太多/过多）
TRANSIENT_ERROR_MARKERS_ALL = TRANSIENT_ERROR_MARKERS + EXT_TRANSIENT_ERROR_MARKERS
# 共享拦截弹窗标记（上游注释：保持短语具体，泛化词会误停 rush 路径）
MANUAL_VERIFICATION_MARKERS = (
    "验证码",
    "滑动验证",
    "安全验证",
    "人机验证",
    "滑块",
    "行为验证",
    "风险验证",
    "风控验证",
    "请完成验证",
)
PENDING_ORDER_MARKERS = (
    "未支付订单",
    "待支付订单",
    "待付款订单",
    "已有未支付订单",
    "已有订单待支付",
)

_BOUNDS_PATTERN = re.compile(
    r"^\[(?P<left>-?\d+),(?P<top>-?\d+)\]"
    r"\[(?P<right>-?\d+),(?P<bottom>-?\d+)\]$"
)


def _center_from_bounds_text(bounds: str) -> Optional[tuple[int, int]]:
    """Android hierarchy bounds 字符串 → 正面积中心点（上游原版）。"""
    match = _BOUNDS_PATTERN.match(bounds or "")
    if match is None:
        return None
    left, top, right, bottom = (
        int(match.group(name)) for name in ("left", "top", "right", "bottom")
    )
    if right <= left or bottom <= top:
        return None
    return ((left + right) // 2, (top + bottom) // 2)


def _node_visible_text(node: ET.Element) -> str:
    """恢复分类用的可见文本负载（text + content-desc，上游原版）。"""
    return " ".join(
        part.strip()
        for part in (node.get("text", ""), node.get("content-desc", ""))
        if part and part.strip()
    )


def _nearest_retry_click_target(
    node: ET.Element,
    *,
    node_text: str,
    parent_map: dict,
    root: ET.Element,
) -> Optional[ET.Element]:
    """解析重试控件，但绝不向上爬到宽泛的页面容器（上游原版）。"""
    if node.get("clickable") == "true":
        return node
    parent = parent_map.get(node)
    if (
        parent is not None
        and parent is not root
        and parent.get("visible-to-user") != "false"
        and parent.get("clickable") == "true"
    ):
        return parent
    # 大麦部分重试文案自身可点，即使 uiautomator 未暴露 clickable=true。
    # 只对精确动作文案（或显式「点击重试」指令）保留该回退（上游原版）。
    if (
        node_text in RETRY_ACTION_TEXTS
        or node_text in EXT_RETRY_ACTION_TEXTS
        or "点击重试" in node_text
    ):
        return node
    return None


def _is_reasonable_error_container(node: ET.Element) -> bool:
    """嵌套节点是否具备本地错误容器语义（上游原版）。"""
    own_text = _node_visible_text(node)
    if any(marker in own_text for marker in TRANSIENT_ERROR_MARKERS_ALL):
        return True
    identity = " ".join(
        (
            node.get("resource-id", ""),
            node.get("class", ""),
            node.get("content-desc", ""),
        )
    ).lower()
    return any(token in identity for token in LOCAL_ERROR_CONTAINER_TOKENS)


def _nearest_common_ancestor(
    first: ET.Element,
    second: ET.Element,
    parent_map: dict,
) -> tuple[Optional[ET.Element], int, int]:
    """最近公共祖先与各自边距（上游原版）。"""
    first_distances: dict = {}
    cursor: Optional[ET.Element] = first
    distance = 0
    while cursor is not None:
        first_distances[cursor] = distance
        cursor = parent_map.get(cursor)
        distance += 1
    cursor = second
    second_distance = 0
    while cursor is not None:
        if cursor in first_distances:
            return cursor, first_distances[cursor], second_distance
        cursor = parent_map.get(cursor)
        second_distance += 1
    return None, 0, 0


def _is_local_transient_retry_pair(
    marker_node: ET.Element,
    action_node: ET.Element,
    click_target: ET.Element,
    *,
    parent_map: dict,
    root: ET.Element,
) -> bool:
    """证明重试控件属于邻近的瞬时错误（上游原版）。

    层级文档根绝不接受为共享容器；除「标记+动作合并同一节点」外，
    两节点必须在一条边内于某个嵌套 XML node 相会——刻意拒绝
    页级错误标记配无关工具栏/内容刷新。
    """
    if marker_node is action_node and click_target is action_node:
        return True
    common, marker_distance, target_distance = _nearest_common_ancestor(
        marker_node, click_target, parent_map
    )
    if common is None or common is root or common.tag != "node":
        return False
    if parent_map.get(common) is root:
        # 顶层 app 壳与层级根结构等价，太宽泛，无法证明动作属于该错误。
        return False
    return (
        marker_distance <= 1
        and target_distance <= 1
        and _is_reasonable_error_container(common)
    )


def find_local_transient_retry_coords(
    root: ET.Element,
) -> Optional[tuple[int, int]]:
    """仅在「本地错误/动作配对」成立时返回重试坐标（上游原版）。

    瞬时标记可以在无法证明配对时仍把页面分类为错误；此时调用方拿到
    None，不得点击。
    """
    parent_map = {child: parent for parent in root.iter() for child in parent}
    visible_nodes = [
        node
        for node in root.iter("node")
        if node.get("visible-to-user") != "false"
    ]
    marker_nodes = [
        node
        for node in visible_nodes
        if any(
            marker in _node_visible_text(node)
            for marker in TRANSIENT_ERROR_MARKERS_ALL
        )
    ]
    if not marker_nodes:
        return None
    for action_node in visible_nodes:
        node_text = _node_visible_text(action_node)
        if not node_text:
            continue
        exact_action = (
            node_text in RETRY_ACTION_TEXTS
            or node_text in EXT_RETRY_ACTION_TEXTS
        )
        phrase_action = any(p in node_text for p in RETRY_ACTION_PHRASES)
        if not (exact_action or phrase_action):
            continue
        click_target = _nearest_retry_click_target(
            action_node, node_text=node_text, parent_map=parent_map, root=root
        )
        if click_target is None:
            continue
        coords = _center_from_bounds_text(click_target.get("bounds") or "")
        if coords is None:
            continue
        if any(
            _is_local_transient_retry_pair(
                marker_node, action_node, click_target,
                parent_map=parent_map, root=root,
            )
            for marker_node in marker_nodes
        ):
            return coords
    return None


# ---- 上游 mobile/recovery.py inspect_transient_failure（移植） ------------


def inspect_transient_failure(root, package: str, activity: str) -> dict:
    """一次层级快照 → 瞬时/验证/待支付/重试坐标分类（上游原版结构）。"""
    if root is None:
        return {
            "transient": False, "manual_verification": False,
            "pending_order": False, "retry_coords": None, "blank": True,
            "package": package, "activity": activity,
            "layout_fingerprint": "blank", "error_markers": (),
        }
    merged_texts = []
    meaningful_node = False
    nodes = list(root.iter("node"))
    for node in nodes:
        if node.get("visible-to-user") == "false":
            continue
        if any(
            (node.get(attr) or "").strip()
            for attr in ("resource-id", "text", "content-desc")
        ) or any(
            node.get(attr) == "true"
            for attr in ("clickable", "scrollable", "checkable")
        ):
            meaningful_node = True
        text = _node_visible_text(node)
        if text:
            merged_texts.append(text)
    merged = " ".join(merged_texts)
    error_markers = tuple(
        sorted(m for m in TRANSIENT_ERROR_MARKERS_ALL if m in merged)
    )
    structural_nodes = tuple(
        (
            node.get("resource-id") or "",
            node.get("class") or "",
            node.get("bounds") or "",
            node.get("clickable") or "",
        )
        for node in nodes
        if node.get("visible-to-user") != "false"
    )
    return {
        "transient": bool(error_markers),
        "manual_verification": any(
            m in merged for m in MANUAL_VERIFICATION_MARKERS
        ),
        "pending_order": any(m in merged for m in PENDING_ORDER_MARKERS),
        "retry_coords": find_local_transient_retry_coords(root),
        "blank": not meaningful_node,
        "package": package,
        "activity": activity,
        "layout_fingerprint": hashlib.sha256(
            repr(structural_nodes).encode("utf-8")
        ).hexdigest()[:20],
        "error_markers": error_markers,
    }


def recover_transient_failure(
    d,
    log,
    *,
    max_attempts: int = 1,
    settle_timeout_s: float = 0.8,
    acted_fingerprints: Optional[set] = None,
) -> dict:
    """不重启会话地恢复加载/网络类错误（上游 recover_transient_failure 移植）。

    快路径只在同一层级出现已知瞬时错误标记、且配对出精确重试控件时点击；
    验证码/人机验证与待支付订单弹窗永不自动操作。相同布局指纹的错误只
    处理一次。返回 dict：state / action / coords / reason。
    """
    acted = acted_fingerprints if acted_fingerprints is not None else set()
    for attempt in range(max(1, int(max_attempts))):
        cur = d.app_current() or {}
        package = cur.get("package", "")
        activity = cur.get("activity", "")
        try:
            xml = d.dump_hierarchy()
            root = ET.fromstring(xml) if xml else None
        except Exception:
            root = None
        snapshot = inspect_transient_failure(root, package, activity)
        if snapshot["pending_order"]:
            log("recovery: 检测到待支付订单弹窗——自动刷新禁用（交人工）")
            return {"state": "pending_order_dialog", "recovered": False}
        if snapshot["manual_verification"]:
            log("recovery: 检测到验证码/人机验证——自动刷新禁用（红线，交人工）")
            return {"state": "manual_verification", "recovered": False}
        if snapshot["transient"] and snapshot["retry_coords"]:
            fp = snapshot["layout_fingerprint"]
            if fp in acted:
                log("recovery: 相同布局指纹的错误已处理过一次——停止自动刷新")
                return {"state": "duplicate_fingerprint", "recovered": False}
            acted.add(fp)
            x, y = snapshot["retry_coords"]
            log(f"recovery: 瞬时页面故障（{','.join(snapshot['error_markers'])}），"
                f"点击重试 ({x},{y})（第 {attempt + 1}/{max_attempts} 次）")
            d.shell(f"input tap {int(x)} {int(y)}")
            time.sleep(settle_timeout_s)
            cur = d.app_current() or {}
            try:
                xml = d.dump_hierarchy()
                root2 = ET.fromstring(xml) if xml else None
            except Exception:
                root2 = None
            after = inspect_transient_failure(
                root2, cur.get("package", ""), cur.get("activity", "")
            )
            if not after["transient"]:
                return {"state": "recovered", "recovered": True,
                        "action": "tap_retry", "coords": (x, y)}
            return {"state": "transient_error", "recovered": False,
                    "action": "tap_retry", "coords": (x, y)}
        if snapshot["transient"]:
            log("recovery: 瞬时错误但无本地配对重试控件——停止自动刷新（fail-closed）")
            return {"state": "transient_error", "recovered": False,
                    "reason": "retry_action_unconfirmed"}
        if snapshot["blank"]:
            log("recovery: 页面空白——不自动恢复")
            return {"state": "blank", "recovered": False}
        return {"state": "clean", "recovered": True}
    return {"state": "unknown", "recovered": False}
