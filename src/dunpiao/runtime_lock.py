"""单实例运行锁（移植自上游 damai_app/runtime_lock.py 的核心）。

为什么需要：同一台手机同时跑两个脚本会互相抢 UI——一个在点确定、另一个
在 dump 或 BACK，两边都会得到错乱状态（实测 2026-11-18：kill 旧进程时发现
两个 e2e 进程同时在跑）。上游用 flock 按「物理设备」加锁，第二个进程立即
失败而不是等待。

本实现保留上游关键语义：
  - 非阻塞（LOCK_NB）：拿不到锁立即返回 False，绝不排队等
  - 锁文件按设备序列号 sha256 命名，放临时目录（用户隔离）
  - 进程退出（含崩溃）内核自动释放，不会留死锁
  - 文件内容只写 pid 作诊断；内核锁才是权威

未移植：上游的 physical_device_id 解析（经 adb 取 ro.serialno 区分
transport serial 与物理设备）。本机单设备直连，serial 已唯一。
"""

from __future__ import annotations

import errno
import hashlib
import os
import tempfile
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - 非 POSIX 平台
    fcntl = None


def _lock_dir() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir) / "dunpiao"
    uid = getattr(os, "getuid", lambda: 0)()
    return Path(tempfile.gettempdir()) / f"dunpiao-{uid}"


class DeviceInstanceLock:
    """按设备序列号的非阻塞独占锁。"""

    def __init__(self, serial: str | None = None, lock_dir: Path | None = None):
        self.serial = (serial or "").strip() or "default"
        self.key = self.serial
        self.lock_dir = Path(lock_dir) if lock_dir is not None else _lock_dir()
        digest = hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:24]
        self.path = self.lock_dir / f"device-{digest}.lock"
        self._file = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

    def acquire(self) -> bool:
        """尝试一次；被占用返回 False（不等待）。"""
        if self._file is not None:
            return True
        if fcntl is None:
            raise RuntimeError("reliable_instance_lock_unavailable: 当前平台不支持 flock")
        self.lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if isinstance(exc, BlockingIOError) or exc.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise
        self._file = handle
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()}\n")
            handle.flush()
        except OSError:
            pass  # 元数据仅诊断用，内核锁才是权威
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._file.close()
        finally:
            self._file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False
