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

## PH-04 初版交付：改版只读探针 v1（2026-11-18）

交付物：`src/dunpiao/selectors.py`（选择器表，每条带来源标注 U/W/N/L）+ `src/dunpiao/probe.py`（只读探针，纯 stdlib 解析，零点击）。

### 上游原版 vs 改版探针（同机同页对照，2026-11-18）

| 维度 | 上游原版 --probe | 改版探针 v1 |
|---|---|---|
| 页面判定 | detail_page ✅ | detail_page ✅（另支持 sku/confirm/login/unknown 粗分） |
| CTA 就绪 | **ready=true（容器级）** | 容器 present+empty、**按钮级未就绪** |
| 预选横幅 | 未检测 | ✅ 检出"设置本次抢票信息，抢票快人一步！" |
| 结构化信息 | 无 | 标题/场馆/场次时间/价格区间（¥288-988）JSON 输出 |
| 实现依赖 | 上游包体系 | 纯 stdlib 解析 + u2 dump，独立可运行 |

**差异解读（重要）**：本机预约阶段详情页实测——CTA 容器 `trade_project_detail_purchase_status_bar_container_fl` 存在但为空（无子节点、无可点击购票节点）。上游 presale_prewarm 以容器为坐标锚（对预热而言合理），但其 ready 语义混合了容器级与按钮级；改版探针显式区分两级，并给出"购票栏未渲染"的明确警告。开票后按钮级就绪判定改由按钮 ID/词表（text+content-desc 双通道）承担。

### 选择器表 v1 要点

- 新增本机实证：`tv_show_time`（场次时间）、`project_price_pre/suffix/char`（价格三段式）、预选横幅 `goto_setinfo_*`——上游常量表均未覆盖
- CTA 词表分三组：READY（立即购买/预订/抢购/选座购买）、RESERVE（立即预约等）、BLOCKED（已售罄/即将开抢/暂未开售）
- 运行：`.venv/bin/python -m src.dunpiao.probe [--serial] [--json] [--save-xml]`；退出码 detail_page=0
- 台账记录：离线样本判定与真机实测结果完全一致（logs/probe_v2_2026-11-18.json）
