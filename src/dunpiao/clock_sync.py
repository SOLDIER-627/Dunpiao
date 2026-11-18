# -*- coding: utf-8 -*-
"""时钟信任评估与开售时刻 → 单调钟映射。

移植自上游 HaTickets mobile/clock_sync.py（commit 76946bf 基线），保持 API 与
阈值一致，仅做中文注释与包内路径适配：
- 采样本地系统时间同步状态（macOS systemsetup / Linux timedatectl），不联网对时；
- 信任分级 trusted / warning / severe / unknown（阈值 0.150s / 1.000s）；
- 把开售 wall-clock 时刻锚定到 time.monotonic()，避免 NTP 跳变破坏倒计时。

约定：offset_seconds = reference_time - local_wall_time；正值表示本地钟偏慢。
"""

from __future__ import annotations

import math
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Callable, Mapping, Optional

WARNING_OFFSET_SECONDS = 0.150
SEVERE_OFFSET_SECONDS = 1.000
WARNING_UNCERTAINTY_SECONDS = 0.250
SEVERE_UNCERTAINTY_SECONDS = 1.000


@dataclass(frozen=True)
class ClockObservation:
    """一次尽力而为的本地时钟质量观测。"""

    offset_seconds: Optional[float] = None
    uncertainty_seconds: Optional[float] = None
    synchronized: Optional[bool] = None
    source: str = "local_system"
    detail: Optional[str] = None

    @property
    def effective_offset_seconds(self) -> float:
        """无实测 offset 时按 0 处理（兼容行为：直接用本地 wall clock）。"""
        if self.offset_seconds is None:
            return 0.0
        value = float(self.offset_seconds)
        return value if math.isfinite(value) else 0.0


@dataclass(frozen=True)
class MonotonicSaleDeadline:
    """锚定到一次单调钟读数的开售时刻。"""

    target_wall_time: datetime
    anchor_wall_time: datetime
    anchor_monotonic: float
    target_monotonic: float
    observation: ClockObservation
    trust_level: str
    trust_reason: str

    @property
    def degrade_to_cta(self) -> bool:
        """severe 信任级：上游语义为降级为纯 CTA 状态轮询（不信任倒计时）。"""
        return self.trust_level == "severe"

    def remaining_seconds(self, monotonic_now: float) -> float:
        return self.target_monotonic - float(monotonic_now)


def _optional_finite_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("clock measurement must be finite")
    return result


def coerce_clock_observation(value: Any) -> ClockObservation:
    """归一化注入 provider 的返回值（ClockObservation 或等价 mapping）。"""
    if isinstance(value, ClockObservation):
        return value
    if isinstance(value, Mapping):
        offset = value.get("offset_seconds", value.get("offset"))
        uncertainty = value.get("uncertainty_seconds", value.get("uncertainty"))
        synchronized = value.get("synchronized")
        if synchronized is not None and not isinstance(synchronized, bool):
            raise ValueError("synchronized must be bool or None")
        return ClockObservation(
            offset_seconds=_optional_finite_float(offset),
            uncertainty_seconds=_optional_finite_float(uncertainty),
            synchronized=synchronized,
            source=str(value.get("source") or "injected"),
            detail=None if value.get("detail") is None else str(value.get("detail")),
        )
    raise TypeError("clock provider must return ClockObservation or mapping")


def _run_local_status_command(command: list, timeout: float = 0.75) -> Optional[str]:
    """短超时运行一条本地时钟状态命令，失败返回 None。"""
    try:
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )
    return output or None


def _macos_sntp_observation() -> Optional[ClockObservation]:
    """本地扩展：systemsetup 无权限时用 sntp（Apple 自家 NTP）实测偏移。

    上游 clock_sync 明确支持注入测量值（模块 docstring："Callers that already
    have a trusted time source can inject a provider"）；此处只是把该入口接到
    macOS 自带的 sntp，不引入第三方 NTP 池。sntp 输出约定与上游一致：
    正 offset = 本地钟慢于参考钟。
    """
    output = _run_local_status_command(["sntp", "-t", "1", "time.apple.com"], timeout=2.5)
    if not output:
        # 实测 sntp 偶发超时：重试一次，仍失败则交回 unknown（不拦截，只是不修正）
        time.sleep(0.2)
        output = _run_local_status_command(["sntp", "-t", "1", "time.apple.com"], timeout=2.5)
        if not output:
            return None
    m = re.search(r"([+-]?\d+\.?\d*)\s*\+/-\s*(\d+\.?\d*)", output)
    if not m:
        return None
    try:
        return ClockObservation(
            offset_seconds=float(m.group(1)),
            uncertainty_seconds=float(m.group(2)),
            synchronized=True,
            source="macos_sntp",
            detail="measured_offset",
        )
    except ValueError:
        return None


@lru_cache(maxsize=1)
def observe_local_clock() -> ClockObservation:
    """检查本地系统时间同步状态（结果缓存）。"""
    system = platform.system()
    if system == "Darwin":
        output = _run_local_status_command(
            ["/usr/sbin/systemsetup", "-getusingnetworktime"]
        )
        normalized = (output or "").lower()
        if "network time: on" in normalized:
            return ClockObservation(
                synchronized=True, source="macos_systemsetup", detail="network_time_on",
            )
        if "network time: off" in normalized:
            return ClockObservation(
                synchronized=False, source="macos_systemsetup", detail="network_time_off",
            )
        # 本机实测（2026-11-18）：systemsetup 需管理员权限，无 sudo 时永远
        # status_unavailable → 回退 sntp 实测偏移，避免本机 0.3s 钟偏在开售时吃亏。
        fallback = _macos_sntp_observation()
        if fallback is not None:
            return fallback
        return ClockObservation(source="macos_systemsetup", detail="status_unavailable")

    if system == "Linux":
        output = _run_local_status_command(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"]
        )
        normalized = (output or "").strip().lower()
        if normalized == "yes":
            return ClockObservation(
                synchronized=True, source="linux_timedatectl", detail="ntp_synchronized",
            )
        if normalized == "no":
            return ClockObservation(
                synchronized=False, source="linux_timedatectl", detail="ntp_not_synchronized",
            )
        return ClockObservation(source="linux_timedatectl", detail="status_unavailable")

    return ClockObservation(source="local_system", detail="status_unsupported")


def sample_clock(provider: Optional[Callable[[], Any]] = None) -> ClockObservation:
    """采样注入 provider 或缓存的本地默认。"""
    if provider is None:
        return observe_local_clock()
    try:
        return coerce_clock_observation(provider())
    except Exception as exc:
        return ClockObservation(
            source="injected_provider", detail="provider_error:%s" % type(exc).__name__,
        )


def assess_clock_trust(observation: ClockObservation) -> tuple:
    """返回 (level, reason)：trusted / warning / severe / unknown。"""
    try:
        offset = _optional_finite_float(observation.offset_seconds)
        uncertainty = _optional_finite_float(observation.uncertainty_seconds)
    except (TypeError, ValueError):
        return "severe", "invalid_measurement"

    if uncertainty is not None and uncertainty < 0:
        return "severe", "invalid_uncertainty"
    if observation.synchronized is False:
        return "severe", "system_clock_not_synchronized"
    if offset is not None and abs(offset) >= SEVERE_OFFSET_SECONDS:
        return "severe", "offset_exceeds_severe_threshold"
    if uncertainty is not None and uncertainty >= SEVERE_UNCERTAINTY_SECONDS:
        return "severe", "uncertainty_exceeds_severe_threshold"
    if offset is not None and abs(offset) >= WARNING_OFFSET_SECONDS:
        return "warning", "offset_exceeds_warning_threshold"
    if uncertainty is not None and uncertainty >= WARNING_UNCERTAINTY_SECONDS:
        return "warning", "uncertainty_exceeds_warning_threshold"
    if observation.synchronized is True:
        return "trusted", "system_clock_synchronized"
    if offset is not None or uncertainty is not None:
        return "trusted", "measurement_within_threshold"
    return "unknown", "clock_quality_unavailable"


def build_monotonic_sale_deadline(
    target_wall_time: datetime,
    anchor_wall_time: datetime,
    anchor_monotonic: float,
    observation: ClockObservation,
) -> MonotonicSaleDeadline:
    """把开售 wall-clock 时刻映射为单调钟 deadline。"""
    if target_wall_time.tzinfo is None or anchor_wall_time.tzinfo is None:
        raise ValueError("target and anchor wall times must be timezone-aware")

    level, reason = assess_clock_trust(observation)
    try:
        effective_offset = _optional_finite_float(observation.offset_seconds) or 0.0
    except (TypeError, ValueError):
        effective_offset = 0.0
    corrected_anchor = anchor_wall_time + timedelta(seconds=effective_offset)
    remaining = (target_wall_time - corrected_anchor).total_seconds()
    return MonotonicSaleDeadline(
        target_wall_time=target_wall_time,
        anchor_wall_time=anchor_wall_time,
        anchor_monotonic=float(anchor_monotonic),
        target_monotonic=float(anchor_monotonic) + remaining,
        observation=observation,
        trust_level=level,
        trust_reason=reason,
    )
