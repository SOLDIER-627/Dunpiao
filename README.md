# dunpiao 蹲票

目标：在用户自己的账号上辅助购买演出票。**大麦先行，猫眼随后。**用户确认同账号近期已在实体 Android 手机的大麦 App 成功登录；USB 控制与真实订单尚未实测。

当前主线是 Mac USB 连接这台真机，先检查在线状态和 scrcpy 人工投屏，再逐步做脱敏页面采样与可停止的单账号 Demo。真机不需要伪装；自动化操作能否被平台接受需单独验证。

- [USB 真机方案与可识别性](docs/architecture/2026-11-16-usb-real-phone-plan.md)
- [任务清单](docs/plan/tasks.md)
- [真机连接清单](docs/setup/2026-11-16-phone-connection-checklist.md)
- [雷电云登录实测](docs/research/2026-11-16-ldcloud-login-observation.md)

本地模拟器与雷电云路线已归档于上级 Ticket 工作区。账号登录、短信验证和支付由用户本人完成；不保存密码、验证码或证件信息。默认停在订单提交前，设备断线和未知页面时安全退出。
