# dunpiao 蹲票

在用户自己的大麦账号上辅助买票：**抢票模式**（开售准点抢）与**回流模式**（缺货登记蹲回流）两条独立路径，共用同一套执行引擎与安全闸门。

合规红线：不做验证码代解、签名逆向、接口直调、代理池、批量注册、自动支付；**付款永远用户手动**；验证/滑块出现即停交人工。

## 两种模式

| 模式 | 入口 | 用途 | 触发条件 |
|---|---|---|---|
| **抢票** | `scripts/rush.py` | 开售准点抢（T0 直击） | `--wait-open HH:MM` 时钟倒计时到点 |
| **回流** | `scripts/reflow.py` | 缺货登记蹲回流票 | 目标票档「缺货登记」消失 |

两条路径触发后走**同一套执行链**：CTA → 确定 → 订单页全字段核对 →（`--submit`）提交 → 收银台即停 → 人工付款。

```
抢票：clock_sync 倒计时 → T0 直点 CTA ─┐
                                      ├→ 同一执行引擎 → 核对 → 提交 → 收银台
回流：周期刷新 SKU → 缺货登记消失 ──────┘
```

## 快速开始

```bash
# 0) 一次性环境
#    Mac + 安卓真机 USB 调试已授权；.venv/bin/python 3.12 + uiautomator2；
#    大麦已登录且实名观演人已在 App 内配好；系统动画三档缩放=0

# 1) 配置：连好 USB、手机停在演出详情页，交给 AI 助手（见「用 AI 助手配置」）
#    或手动提取当前页信息（只读零点击）确认场次/票档序号
.venv/bin/python scripts/show_info.py --serial <serial>

# 2) 演练（不提交，停在提交前核对）
.venv/bin/python scripts/rush.py --show-tag <tag> --expected-total 588.00

# 3) 抢票：开售准点（付款人工）
.venv/bin/python scripts/rush.py --wait-open 15:00 --submit \
    --show-tag <tag> --expected-total 488.00

# 4) 回流：蹲缺货登记的票档
.venv/bin/python scripts/reflow.py --submit \
    --show-tag <tag> --expected-total 488.00 \
    --session-index 1 --expect-session-date 2026.11.21 \
    --reflow-interval 2 --reflow-refresh 15 --reflow-max-minutes 300
```

详细说明：[抢票模式](docs/抢票模式.md) · [回流模式](docs/回流模式.md) · [原理与流程](docs/原理与流程.md) · [AI 助手配置](docs/AI助手配置.md)

## 用 AI 助手配置（推荐）

连好 USB、把手机停在大麦演出详情页，然后直接对多模态 AI 助手说人话即可——
读页面、认场次、认票档、写配置都由它做，你只负责逐项确认：

```
帮我配置一个新演出。手机已连好，大麦停在目标演出详情页。
目标：11.21 周六场，看台 588 这一档。
请用 new-show-setup skill：先 capture 采集 → 把标题/场馆/场次/票档逐项列出来
跟我确认 → 我确认后再 apply 写配置，show_tag 用 forever_588_20261121
```

```
大麦停在详情页了，我要蹲「周六 看台488」。
用 show-info-extract skill 提取页面信息；当前页看不到票档就自己点进 SKU 面板
提取（只点导航，别点确定），提取完退回来。告诉我 session_index 和 price_index，
再给我一条可以直接跑的 reflow.py 命令（先不加 --submit）。
```

两个 skill：`.agents/skills/show-info-extract/`（提取）、`.agents/skills/new-show-setup/`（录入）。
更多示例提示词与 AI 边界：[docs/AI助手配置.md](docs/AI助手配置.md)

## 配置

`config.local.jsonc`（gitignored，敏感信息不入库）：

| 键 | 说明 |
|---|---|
| `keyword` / `date` / `price` / `price_index` | 搜索关键词、场次日期子串、目标票价、票档序号（0 起，面板从上到下） |
| `session_index` | 场次序号（两级面板：场次→票档） |
| `target_title` / `target_venue` | 目标演出/场馆（档案用） |
| `users` | 观演人姓名列表（**敏感**，订单核对用） |

新演出录入用向导（逐项确认后才写配置）：

```bash
.venv/bin/python -m src.dunpiao.show_wizard capture   # 手机停在详情页，只读零点击
.venv/bin/python -m src.dunpiao.show_wizard apply --tag <show_tag> --keyword <词> \
  --date <日期子串> --price <价> --price-index <序号> --title <标题> --venue <场馆>
```

## 安全机制（两模式共用）

- **拦在提交前的核对**（真正的闸门）：金额=expected_total、×1张、场次日期（`--expect-session-date`）、观演人在页且各一次、checkbox 实勾数≥所需位数；任一不过→停机不提交
- **提交一次**：点击后只读验证，不再发出任何点击（防重复下单）
- **提交后五分类**：支付页信号=成功 / 售罄 / 验证码 / 未支付无法归属 / 结果未知（交人工核实订单列表）
- **提交前四类阻塞弹窗**：授权弹窗、待支付弹窗、验证码、瞬时错误（只有瞬时错误会在提交前恢复，其余即停）
- **单实例锁**：同一设备只允许一个运行器，第二个立即失败（避免互抢 UI）
- **收银台即停**：付款永远人工

## 参考代码仓

本项目是**参考上游、不自造**的产物：方法骨架来自下列开源仓库，按本机真机实测改造。
固定基线与取舍记录见 [原理与流程](docs/原理与流程.md) 第 7 节。

### 主基线（代码级参考）

| 仓库 | 采用内容 |
|---|---|
| **[currycan/HaTickets](https://github.com/currycan/HaTickets)** — 固定 commit `76946bf`（Mobile 端） | 本项目的方法主线：`fast_pipeline` 四阶段热路径、`page_probe` 状态分类与阻塞弹窗词表、`recovery` 瞬时错误配对恢复、`orchestrator.verify_order_result` 提交后只读验证、`runtime_lock` 单实例锁、`event_navigator.select_session` 场次匹配、`attendee_selector` 观演人位数、`price_selector` 票档不可购词表、`buy_button_guard` 文案护栏、`sale_waiter` 开售等待骨架 |

代码内的对应关系逐条列在 [原理与流程 §7](docs/原理与流程.md)（`engine.py` ↔ `fast_pipeline.py`、`recovery.py` ↔ `page_probe.py + recovery.py` 等）。

### 情报与设计参考（未直接采用代码）

| 仓库 | 借鉴点 |
|---|---|
| [WECENG/ticket-purchase](https://github.com/WECENG/ticket-purchase) | Appium 侧大麦选择器实证（资源 ID / 文案），用于交叉验证选择器表 |
| [Lzhimie/damai-ticket-helper](https://github.com/Lzhimie/damai-ticket-helper) | 大麦 9.x 适配经验、票价图片化与 `session_index` 概念来源 |
| [Szymou/NNBS](https://github.com/Szymou/NNBS) | 回流监测设计要点（二次回流、「我知道了」弹窗自动点、场次过滤）与开售时间对齐 |
| [yanzilee/damaiTickets](https://github.com/yanzilee/damaiTickets) | 移动端页面探测思路；其 Web/H5 路线受风控限制的反例 |
| [MakiNaruto/Automatic_ticket_purchase](https://github.com/MakiNaruto/Automatic_ticket_purchase) | Web/Selenium 路线代表；仅登录态与余票监控价值，购票受限 |
| [Guyungy/damaihelper](https://github.com/Guyungy/damaihelper) | Web 控制台工程骨架参考 |
| [DracoYan-111/damai_grab_votes](https://github.com/DracoYan-111/damai_grab_votes) | 大麦「预选」机制情报 |
| [Pactum7/ticket-grabbing](https://github.com/Pactum7/ticket-grabbing)、[TsungShr/ticket-sniper](https://github.com/TsungShr/ticket-sniper)、[xinyi-eng/damai-mcp](https://github.com/xinyi-eng/damai-mcp) | 提交闸门、拟人节奏等设计互证 |

### 工具与协议

| 项目 | 用途 |
|---|---|
| [openatx/uiautomator2](https://github.com/openatx/uiautomator2) | 真机 UI 自动化直连（本项目的执行层） |
| [appium/appium-uiautomator2-driver](https://github.com/appium/appium-uiautomator2-driver) | 底层同为 UiAutomator2 的旁证（我们省掉 Appium 中间层） |
| [Genymobile/scrcpy](https://github.com/Genymobile/scrcpy) | 真机镜像/调试辅助（非运行依赖） |

### 明确不采用

- **Frida/Xposed 注入、签名逆向、接口直调（mtop/baxia）、验证码代解、代理池、批量注册**——违反合规红线，且社区实证大麦检测后静默限流
- **Web/Selenium 与 H5 路线**——风控强、稳定性差，仅保留余票监控价值

## 常见 STOP 与处置

| STOP 信息 | 原因 | 处置 |
|---|---|---|
| 不在详情页 | 手机不在目标演出详情页 | 手动导航后重跑 |
| 该设备已有另一个运行器在跑 | 单实例锁被占用 | `kill <pid>` 后重跑 |
| 确认页未出现 | 无票/预约态/弹窗拦截 | 看屏幕确认 |
| 核对未全通过 | 金额/场次/观演人不符 | 按日志里 `s3: 订单核对 {...}` 逐项核对 |
| 提交后未检测到收银台（结果未知） | 大麦「提交中」慢或提交失败弹窗挂屏 | 人工点弹窗「继续尝试」或在大麦「我的→待付款」核实 |
| 时钟信任 severe | 设备/Mac 时钟未同步 | 同步时间后重跑 |
| 回流监听超时 | 到 `--reflow-max-minutes` 未等到回流 | 属预期；延长时长或换票档 |

## 目录

```
README.md                本文（总览 + 快速开始）
docs/抢票模式.md          抢票：开售倒计时、预选、命令速查
docs/回流模式.md          回流：监听机制、两级面板、刷新节奏
docs/原理与流程.md        机制细节、设计纪律、耗时模型、上游对应
docs/AI助手配置.md        Skill 使用指南 + 示例提示词
（本文末「参考代码仓」列出全部上游来源）
scripts/rush.py          抢票入口
scripts/reflow.py        回流入口
scripts/show_info.py     页面信息提取（只读）
src/dunpiao/engine.py    两模式共用执行引擎
src/dunpiao/reflow.py    回流监听核心
src/dunpiao/runtime_lock.py  单实例锁
src/dunpiao/clock_sync.py    开售时钟（抢票用）
src/dunpiao/{probe,recovery,selectors,coords_cache,show_wizard}.py
.agents/skills/          新演出录入 / 信息提取 skill
```
