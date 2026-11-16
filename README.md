# dunpiao 蹲票

目标：在用户自己的账号上辅助购买演出票。**当前先做猫眼**：用户报告猫眼 App 能登录，先恢复一台 Android 15 ARM64 本地模拟器并独立验证该设备的登录态；真实订单尚未实测。

当前主线是单台 Google Play AVD 上的猫眼 App。先人工登录、采集脱敏页面，再做可停止的单账号 Demo。大麦 USB 真机方案暂缓。

- [猫眼模拟器方案](docs/architecture/2026-11-16-maoyan-emulator-plan.md)
- [猫眼开源实现核查](docs/research/2026-11-16-maoyan-open-source-review.md)
- [任务清单](docs/plan/tasks.md)
- [模拟器使用](docs/setup/2026-11-16-maoyan-emulator-setup.md)
- [USB 真机大麦候选方案](docs/architecture/2026-11-16-usb-real-phone-plan.md)

先前大麦本地模拟器与雷电云失败记录归档于上级 Ticket 工作区；新猫眼 AVD 不继承旧数据。账号登录、短信验证和支付由用户本人完成；不保存密码、验证码或证件信息。默认停在订单提交前，设备断线和未知页面时安全退出。
