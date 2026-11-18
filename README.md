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

连好 USB、把手机停在大麦演出详情页，然后对多模态 AI 助手说一句话即可。
按模式选一条：

**抢票**
```
手机已连好，大麦停在目标演出详情页。帮我配抢票：11.21 周六场，看台 588。
用 skill 提取信息，跟我确认后写配置。
```

**回流**
```
手机已连好，大麦停在该演出页。帮我配回流蹲守：周六场，看台 488（现在是缺货登记）。
用 skill 确认场次和票档序号，然后给我一条可以直接跑的 reflow.py 命令。
```

AI 会提取页面（必要时点进 SKU 面板，只点导航不点确定）→ 逐项跟你确认标题/场馆/
场次/票档 → 写 `config.local.jsonc` → 给出可复制的运行命令。

前置准备与 AI 边界：[docs/AI助手配置.md](docs/AI助手配置.md)

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

本项目是「参考上游、不自造」的产物：方法骨架来自开源实现，按本机真机实测改造。

| 仓库 | 参考内容 |
|---|---|
| **[currycan/HaTickets](https://github.com/currycan/HaTickets)** @ `76946bf`（Mobile） | **主基线**：`fast_pipeline` 四阶段热路径、`page_probe` 弹窗词表、`recovery` 瞬时错误配对、`verify_order_result` 提交后只读验证、`runtime_lock` 单实例锁、`event_navigator` 场次匹配、`attendee_selector` 观演人位数 |
| [WECENG/ticket-purchase](https://github.com/WECENG/ticket-purchase) | 大麦选择器实证（资源 ID / 文案），交叉验证 |
| [Szymou/NNBS](https://github.com/Szymou/NNBS) | 回流监测要点（二次回流、「我知道了」自动点）、开售时间对齐 |
| [Lzhimie/damai-ticket-helper](https://github.com/Lzhimie/damai-ticket-helper) | 大麦 9.x 适配、票价图片化与 `session_index` 概念 |
| [openatx/uiautomator2](https://github.com/openatx/uiautomator2) | 执行层（真机 UI 直连） |

逐模块对应关系见 [原理与流程 §7](docs/原理与流程.md)。**不采用**：Frida/Xposed 注入、签名逆向、接口直调、验证码代解、代理池、批量注册；Web/Selenium 与 H5 路线（风控强）。

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
