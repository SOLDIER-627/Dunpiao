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
