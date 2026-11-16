# 安卓环境记录

2026-11-16，Apple Silicon Mac。仓库内的 `scripts/doctor.py` 可重复执行以下检查。

| 项目 | 当前结果 |
|---|---|
| Python | 3.14.7 |
| Java | OpenJDK 21.0.12.1 |
| Android SDK / adb / emulator | 未安装或不在 PATH |
| Android Studio | 未安装 |
| 安卓设备 | 未连接 |

官方 Android 下载页提供 Mac ARM 命令行工具，可通过 `sdkmanager` 安装 SDK、模拟器和 ARM64 系统镜像。下载及使用前需接受 Android SDK 许可。官方安装与启动文档：

- [Android Studio / 命令行工具下载](https://developer.android.com/studio/)
- [Android Studio 安装说明](https://developer.android.com/studio/install)
- [模拟器命令行说明](https://developer.android.com/studio/run/emulator-commandline)

下一次更新应补充：SDK 路径、工具版本、AVD 名称、Android 版本、`adb devices` 结果，以及大麦 App 在模拟器中的安装/登录验证。账号、验证码和证件信息不得写入此文件。
