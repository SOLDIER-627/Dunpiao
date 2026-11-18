# 安卓环境记录

> **历史记录：**本地模拟器路线已于 2026-11-16 终止，SDK、镜像和 AVD 已删除。以下操作与路径不再可用；见 [归档说明](../../archive/emulator-2026-11-16/README.md)。

更新：2026-11-16。Apple Silicon Mac；项目内安装 SDK 和 AVD，无需 Android Studio。

| 项目 | 当前结果 |
|---|---|
| Android SDK | `/Users/Admin/Desktop/work/Ticket/.android-sdk` |
| AVD | `Ticket_API35`，Pixel 7 配置 |
| 系统 | Android 15，ARM64 (`arm64-v8a`)，Google APIs 镜像 |
| adb / emulator | platform-tools 37.0.1 / emulator 37.2.13 |
| 设备连接 | `emulator-5554 device`，2026-11-16 已验证 |
| 大麦 App | `cn.damai` 9.0.38，已安装；登录遭遇“亲，访问被拒绝” |
| 用户偏好 | 简体中文、屏幕三键、本机键盘；见 `模拟器使用偏好.md` |

一键启动脚本：`scripts/start-emulator.command`。SDK、AVD、运行日志均不入 Git；不要将账号、验证码、证件号写入仓库。登录问题的事实记录在 `pagesamples/emulator-login.md`。
