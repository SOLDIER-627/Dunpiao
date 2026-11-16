#!/usr/bin/env python3
"""Read-only checks for the local Android ticket assistant environment."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def run_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=8, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def adb_devices(adb: str | None) -> list[dict[str, str]]:
    if not adb:
        return []
    try:
        result = subprocess.run(
            [adb, "devices"], capture_output=True, text=True, timeout=8, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices.append({"id": parts[0], "state": parts[1]})
    return devices


def collect() -> dict[str, object]:
    project_root = Path(__file__).resolve().parent.parent
    project_sdk = project_root / ".android-sdk"
    sdk_candidates = [
        str(project_sdk),
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        str(Path.home() / "Library/Android/sdk"),
    ]
    sdk_roots = [str(Path(p).expanduser()) for p in sdk_candidates if p and Path(p).expanduser().exists()]
    def tool(name: str, relative: str) -> str | None:
        local_path = project_sdk / relative
        return str(local_path) if local_path.exists() else shutil.which(name)

    adb = tool("adb", "platform-tools/adb")
    emulator = tool("emulator", "emulator/emulator")
    sdkmanager = tool("sdkmanager", "cmdline-tools/latest/bin/sdkmanager")
    return {
        "python": run_version([shutil.which("python3") or "python3", "--version"]),
        "java": run_version([shutil.which("java") or "java", "-version"]),
        "adb": {"path": adb, "version": run_version([adb, "version"]) if adb else None},
        "emulator": {"path": emulator, "version": run_version([emulator, "-version"]) if emulator else None},
        "sdkmanager": {"path": sdkmanager},
        "sdk_roots": sdk_roots,
        "android_studio": Path("/Applications/Android Studio.app").exists(),
        "devices": adb_devices(adb),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Android development prerequisites")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args()
    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for key, value in data.items():
            print(f"{key}: {value}")
    return 0 if data["adb"]["path"] and data["emulator"]["path"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
