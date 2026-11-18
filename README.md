# dunpiao 蹲票

目标：在用户自己的账号上辅助购买演出票。**当前先做大麦实体安卓手机**：以 HaTickets Mobile 为主代码基线，结合其他开源实现并按真机实测改造。猫眼作为后续真机适配。

2026-11-18 已只读核对 USB 连接与原有登录态；Python 3.12 隔离环境已建，`--probe` 页面探测尚未执行。下一阶段由 Pi 编码，见上级 Ticket 工作区的[交接文档](../docs/architecture/Pi编码交接_2026-11-18.md)。真实订单未验证。

- [HaTickets 真机接入方案](docs/architecture/2026-11-17-hatickets-real-phone-plan.md)
- [HaTickets 开源核查](docs/research/2026-11-17-hatickets-real-phone-review.md)
- [多仓融合与代码改造](docs/research/2026-11-17-multi-repo-integration.md)
- [任务清单](docs/plan/tasks.md)
- [USB 首轮接入清单](docs/setup/2026-11-17-hatickets-usb-checklist.md)
- [历史路线归档](ARCHIVE.md)

大麦模拟器、雷电云与猫眼模拟器尝试已归档于上级 Ticket 工作区。账号登录、短信验证和支付由用户本人完成；不保存密码、验证码或证件信息。首轮 `--probe` 停在购票入口前，设备断线和未知页面时安全退出。
