# dunpiao 整体计划

更新：2026-11-17。当前先做**大麦实体安卓手机 USB 接入**，以 HaTickets Mobile 为主代码基线，融合其他开源实现并按真机结果改造。唯一当前任务清单见[任务清单](tasks.md)，详细设计见[真机方案](../architecture/2026-11-17-hatickets-real-phone-plan.md)与[多仓融合清单](../research/2026-11-17-multi-repo-integration.md)。

## 阶段

1. 猫眼本地模拟器尝试归档并清理运行资源；ADB Platform-Tools 留作真机连接。
2. 用户在已登录大麦的实体安卓手机上开启 USB 调试并授权 Mac；只读检查设备与 App 人工使用。
3. 准备项目隔离的 Python 环境，固定 HaTickets 代码与依赖，记录上游只读 `--probe` 基线。
4. 对照 WECENG/Lzhimie 的大麦定位与流程，根据真机样本改造 HaTickets 并核对订单摘要。
5. 用户决定后做一次人工监督的真实订单验证，支付由用户本人完成；再参考猫眼开源流程做真机适配，最后考虑可视化控制。

历史模拟器和雷电云结果见上级 Ticket 工作区归档。2026-11-18 真机 USB 与大麦人工浏览已通过；编码接续见上级 Ticket 工作区的[Pi 交接](../../../docs/architecture/Pi编码交接_2026-11-18.md)。u2 探测和订单流程尚未运行。
