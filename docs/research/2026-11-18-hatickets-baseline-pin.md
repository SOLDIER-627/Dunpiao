# HaTickets 上游基线固定记录

固定日期：2026-11-18。执行：PH-02（见[编码交接](../architecture/Pi编码交接_2026-11-18.md)）。

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/currycan/HaTickets |
| 固定 commit | `76946bfb3594b4a6a71bb72d37707b75773604fa`（`76946bf` "Harden and accelerate the mobile ticket flow (#60)"，master HEAD @ 2026-11-18） |
| 许可证 | Apache-2.0（含 NOTICE） |
| 本地 checkout | `reference/HaTickets/`（浅克隆，只读参考与原版基线运行；不入本项目 git） |
| 上游 Python 约束 | `>=3.8,<3.14` —— 本机 `.venv` 3.12.14 满足 |
| 上游依赖约束 vs 本机实装 | `uiautomator2 ^3.2` ↔ 3.7.1 ✅；`adbutils ^2.9` ↔ 2.12.0 ✅；`selenium >=4.22,<4.28` ↔ 4.27.1 ✅（本日为 mobile 运行补装） |
| Poemetry/Poetry | 未使用 Poetry；以 `.venv` + pip 满足同等约束（差异已记录） |

原版 `--probe` 结果：**待 PH-03**（需用户在手机上打开精确目标详情页后运行）。

对照台账约定：后续每项上游改造在此追加一节（变更模块 / 页面样本 / 触发场景 / 前后结果 / 回退方式）。

## 原版 --probe 结果（2026-11-18，PH-03 上游半程）

- **一次通过**：Android 16 / 大麦 9.0.38.6 上，上游原版 `--probe`（`76946bf`）正确识别 `detail_page`、确认 CTA 控件就绪、停在购票点击前，耗时 0.63s，exit=0。日志：`logs/probe_upstream_2026-11-18.log`。
- **关键控件实证**：`cn.damai:id/trade_project_detail_purchase_status_bar_container_fl` 在本机（Xiaomi 14 / Android 16 / 大麦 9.0.38.6）**真实存在且可定位**——调研阶段"该资源 ID 跨大版本稳定"的结论在本机获得直接验证；上游 issue #41/#61 的失效问题未在本机复现（至少 CTA 层面）。
- **预约阶段行为**：演出处于预约抢票阶段（CTA=立即预约），上游 presale_prewarm 判定 `ready=true`——预约分支可用（对照：WECENG 明确未处理预约）。
- **本项目只读诊断对照**：`scripts/diagnose_android_login.py` 通过（需 PATH 前置 platform-tools），环境快照：Android 16 / API 36 / user+release-keys / 自动对时开启 / 无代理 / 无 Private DNS。日志：`logs/diagnose_2026-11-18.log`。
- **运行方式备忘**：`cd reference/HaTickets/mobile && PYTHONPATH=. HATICKETS_CONFIG_PATH=<本地配置> .venv/bin/python -m damai_app --serial <serial>`；本地配置 `config.local.jsonc`（gitignored，含真实观演人信息，由用户本人维护）。
- **改版探针对照**：并入 PH-04（改版探针即融合适配层初版交付物），对照基准=本节记录。
- 安全注：u2 首次连接已在设备安装 `com.github.uiautomator` 辅助服务（预期暴露面）；后续人工验证大麦使用无异常后按需卸载。
