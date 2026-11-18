# 开发任务

更新：2026-11-18。当前主线为**大麦 App + 实体安卓手机 + Mac USB**；以 HaTickets Mobile 为主代码基线，融合其他仓库并按真机实测改造。下一阶段编码交给 Pi，见[编码交接](docs/architecture/Pi编码交接_2026-11-18.md)、[真机方案](docs/architecture/HaTickets真机接入方案_2026-11-17.md)和[多仓融合清单](docs/research/多仓方案融合与HaTickets改造清单_2026-11-17.md)。

| ID | 状态 | 任务 | 验收标准 |
|---|---|---|---|
| AR-02 | 完成 | 归档猫眼本地模拟器尝试并清理运行资源 | [归档记录](archive/maoyan-emulator-2026-11-17/README.md)；仅保留真机所需 ADB |
| HT-00 | 完成 | 核对 HaTickets Mobile 路线 | [核查文档](docs/research/HaTickets真机路线核查_2026-11-17.md)明确 u2、环境、`--probe`/`--commit` 的语义 |
| HT-01 | 完成 | 制定多仓融合与改造方案 | [模块清单](docs/research/多仓方案融合与HaTickets改造清单_2026-11-17.md)明确主代码基线、次要来源、改造范围与验收顺序 |
| PH-00 | 完成 | 用户确认实体手机的大麦 App 已登录且可以人工浏览 | 2026-11-18 用户确认“可以”，ADB 读到前台包名 `cn.damai` |
| PH-01 | 完成 | 手机 USB 连接 Mac 并授权调试 | 2026-11-18 官方 ADB 只显示一台实体 Xiaomi 14，状态 `device`；Android 16，大麦 9.0.38.6 |
| PH-02 | 完成 | 隔离环境与 HaTickets 上游代码基线 | 2026-11-18 完成：`.venv`（Python 3.12.14）满足上游约束；上游 checkout 固定 commit `76946bf`（Apache-2.0），依赖 u2 3.7.1 / adbutils 2.12.0 / selenium 4.27.1 全部满足；入口 `--help` 与全模块导入冒烟通过；`mobile/config.jsonc` 保持占位值不入库；台账见[基线固定](docs/research/HaTickets基线固定_2026-11-18.md) |
| PH-03 | 完成（上游半程） | 上游原版和本项目改版只读 `--probe` 对照 | 2026-11-18：上游原版 `--probe` **一次通过**（Android 16 / 大麦 9.0.38.6，识别 detail_page、CTA 控件就绪、0.63s、停在购票点击前）；资源 ID `trade_project_detail_purchase_status_bar_container_fl` 本机实证存在；预约分支 ready；本项目诊断脚本通过。改版探针对照并入 PH-04（改版探针=融合适配层初版交付物），结果见[基线固定](docs/research/HaTickets基线固定_2026-11-18.md) |
| PH-04 | 待开始 | 融合 WECENG/Lzhimie 的大麦页面定位与流程，改造 HaTickets 适配层；**初版交付含改版只读探针并与上游基线对照** | 场次、票价、人数、观演人和金额匹配；未知页安全停止；每项改动有样本和回退说明 |
| PH-05 | 后续独立验收 | 单次人工监督的订单提交 | 只在用户确定目标后运行；最多创建一张目标订单，支付由用户完成 |
| MY-PH | 后续 | 参考 Pactum7 做猫眼真机适配 | 复用设备层和运行控制，依据猫眼真机页面样本另写适配器 |
| UX-PH | 后续 | 参考 Lzhimie/Guyungy 做可视化控制 | CLI 真机流程稳定后，提供可停止、可查看状态和日志的界面 |

所有已停止路线见[归档索引](archive/README.md)。真机 USB 和人工大麦浏览已通过；u2 真机连接命令被中断，HaTickets 原版 `--probe` 尚未运行，Android 16 自动化兼容性待 Pi 验证。
