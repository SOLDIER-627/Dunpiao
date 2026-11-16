#!/usr/bin/env python3
"""Read-only Android environment summary for comparing Damai login devices."""

import argparse
import json
import shutil
import subprocess
import sys


def adb(*args):
    try:
        completed = subprocess.run(
            ["adb", *args], capture_output=True, text=True, timeout=12, check=False
        )
    except subprocess.TimeoutExpired:
        return "<timeout>"
    if completed.returncode:
        return "<unavailable>"
    return completed.stdout.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Read Android OS, app version, time and proxy settings without logging in"
    )
    parser.add_argument("--serial", help="ADB device serial when more than one device is connected")
    args = parser.parse_args()

    if not shutil.which("adb"):
        sys.exit("adb 未安装。先安装 Android 官方 Platform-Tools；无需模拟器镜像。")

    lines = adb("devices").splitlines()[1:]
    devices = [line.split()[0] for line in lines if len(line.split()) >= 2 and line.split()[1] == "device"]
    serial = args.serial
    if serial is None:
        if len(devices) != 1:
            sys.exit("需要恰好一台在线设备；多设备时请用 --serial 指定。")
        serial = devices[0]
    elif serial not in devices:
        sys.exit("指定设备未处于在线状态；请检查 adb devices 和手机授权。")

    def read(*command):
        return adb("-s", serial, "shell", *command).strip()

    def version():
        dump = read("dumpsys", "package", "cn.damai")
        for line in dump.splitlines():
            if "versionName=" in line:
                return line.strip().split("versionName=", 1)[1].split()[0]
        return "<not installed or unavailable>"

    proxy = read("settings", "get", "global", "http_proxy")
    # A configured proxy is a diagnostic clue; avoid printing its host/credentials.
    proxy_state = "configured" if proxy not in ("", ":0", "null", "<unavailable>") else "none or unavailable"

    result = {
        "device_serial": "<redacted>",
        "android_release": read("getprop", "ro.build.version.release"),
        "android_api": read("getprop", "ro.build.version.sdk"),
        "model": read("getprop", "ro.product.model"),
        "build_type": read("getprop", "ro.build.type"),
        "build_tags": read("getprop", "ro.build.tags"),
        "damai_version": version(),
        "auto_time": read("settings", "get", "global", "auto_time"),
        "auto_time_zone": read("settings", "get", "global", "auto_time_zone"),
        "http_proxy": proxy_state,
        "private_dns_mode": read("settings", "get", "global", "private_dns_mode"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
