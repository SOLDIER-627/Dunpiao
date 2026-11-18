# dunpiao 蹲票

目标：在用户自己的账号上辅助购买演出票。**当前先做大麦实体安卓手机**：以 HaTickets Mobile 的真机 uiautomator2 代码为主线，结合其他开源仓库的页面与流程经验，并依据本机实测修改。猫眼保留后续适配计划。

合规红线：不做验证码代解、签名逆向、接口直调、代理池、批量注册、自动支付；**付款永远用户手动**；验证/滑块出现即停，交人工。

## 当前状态（2026-11-18）

端到端单进程脚本完成并完全采用上游 fast_pipeline 方法；真机实战（林忆莲武汉站 15:00 真开售）全链验证：T0 直点→订单页核对全过→提交点击成功。实战口径 **T0→订单确认页 1.11s**（缓存路径），含收银台即停。完整演进见[上游方法重构与坐标缓存归档](docs/architecture/上游方法重构与坐标缓存归档_2026-11-18.md)。

## 环境准备（一次性）

1. **Mac + 安卓真机 USB**：设备开启 USB 调试并授权；`adb` 在 `.android-sdk/platform-tools/adb`，设备序列号写入命令或 config（本机 `a0033f8b`）。USB 偶发掉线：`adb devices` 空列表时物理重插。
2. **Python 环境**：`.venv/bin/python`（3.12），依赖 uiautomator2。设备端 uiautomator server 首次连接自动安装。
3. **大麦 App**：已登录；实名观演人已在 App 内配置好（脚本只勾选、不新增）。
4. **系统动画已关**（开发者选项三档缩放=0）——rush 隐含前提。

## 配置

`config.local.jsonc`（gitignored，敏感不入库）：

| 键 | 说明 |
|---|---|
| `keyword` / `date` / `price` / `price_index` | 搜索关键词、场次日期子串、目标票价、票档序号（0 起，预约态未经文本验证时仅作兜底） |
| `target_title` / `target_venue` | 目标演出/场馆（档案用） |
| `users` | 观演人姓名列表（**敏感**，核对用） |

新演出录入用向导（AI 逐项确认后才写配置）：

```bash
.venv/bin/python -m src.dunpiao.show_wizard capture   # 手机停在详情页，只读零点击
.venv/bin/python -m src.dunpiao.show_wizard apply --tag <show_tag> --keyword <词> \
  --date <日期子串> --price <价> --price-index <序号> --title <标题> --venue <场馆>
```

预约态预检的局限（价格文本为空/无选中态标记/坐标受滚动影响）见 skill 文档 `.agents/skills/new-show-setup/SKILL.md`。

## 标准流程（默认三击）

**前置准备（人工，开售前完成）**：大麦 App 内完成**预约 + 预选**（目标场次+票档，如「12.6 周日场 看台 488」）。预选设置后，开售时面板打开即目标档，脚本全程只需 3 次点击：

```
① CTA（详情页购票按钮）  ② 确定（SKU 面板）  ③ 立即提交（订单页）
                          第 4 步：付款——永远人工
```

**开售前预填坐标**（预约态即可，只信 CTA）：

```bash
.venv/bin/python scripts/e2e_run.py --capture-coords --show-tag <show_tag>
```

**演练（无提交，~2s，停在提交前）**：

```bash
.venv/bin/python scripts/e2e_run.py --show-tag <show_tag> --expected-total <票价>.00
```

**开抢（T0 准点直击）**：

```bash
.venv/bin/python scripts/e2e_run.py --wait-open <HH:MM> --submit \
  --show-tag <show_tag> --expected-total <票价>.00
```

流程：clock_sync 等待 → T0 直点 CTA → 面板打开（预选已生效）→ 只点确定 → 订单页全字段核对（金额/张数/观演人/实勾数）→ 核对全过才点提交 → 收银台即停 → **人工付款**。

## 命令速查

| 命令 | 作用 |
|---|---|
| `--wait-open HH:MM`（或 `YYYY-MM-DD HH:MM`） | 开售等待：T0 准点直击（时钟 severe 默认拒绝） |
| `--submit` | 真实提交（默认关闭；提交前核对全过才点击，单次不盲重试） |
| `--preselect` / `--no-preselect` | 预选直点默认**开**；未预约预选的演出加 `--no-preselect` |
| `--capture-coords` | 测量模式：预约态取坐标写缓存即停 |
| `--expected-total 488.00` | 订单金额核对基准（默认 780.00，**每场必改**） |
| `--show-tag <tag>` | 缓存键/审计标识 |
| `--clear-record` | 可选审计标记（不再拦截提交） |
| `--ignore-clock-trust` | 时钟 severe 时强行继续（默认拒绝） |

## 耗时基准（真机实测，Xiaomi 14 / HyperOS）

| 分段 | 实测 |
|---|---|
| T0 直点 CTA | 偏差 ~1-45ms |
| CTA→面板打开 | 0.15-0.30s |
| 驻留+首批连点（预选直点确定） | 0.4s + 0.9s 窗口内命中 |
| **预选生效：T0→订单确认页** | **预期 ~1.0s**（sandy 实战 T0+2.5s 含一次预选未命中） |
| 提交→收银台 | 2.78s（大麦建单地板，不可优化） |

每次运行结束输出「=== 耗时明细 ===」表（相对 CTA 点击的 t+/步长）。

## 安全机制

- **拦在提交前的核对**（真正的闸门）：金额=expected_total、×1张、观演人在页且各一次、checkbox 实勾数≥观演人数；任一不过→停机，不点提交
- **提交审计**：submit_record.json 只记审计不拦截（App 自身有待支付订单拦截；订单实况用户人工确认）
- **收银台即停**：到收银台终止；滑块/安全验证出现即停交人工
- **瞬时弹窗自动重试**（上游 transient_error 同类）：提交后若出现「抢票人数太多/繁忙」类弹窗，自动点击「继续尝试/重新尝试/再试一次」按钮恢复（最多 5 次，仍回到收银台等待）；验证类弹窗仍即停
- **CTA 文案护栏**：预约/预售态文案拦截点击
- **缓存自愈链**：连点未确认→重测 dump（¥价格文本匹配选档，对滚动免疫）→再连点→元素回退→STOP

## 常见 STOP 与处置

| STOP 信息 | 原因 | 处置 |
|---|---|---|
| 不在详情页 | 手机不在目标演出详情页 | 手动导航后重跑 |
| 确认页未出现（连点+重测+元素回退均超时） | 预约态/无票/弹窗拦截 | 看屏幕；预约态属预期 |
| 提交后未检测到收银台 | 大麦「提交中」慢（等待已放宽 20s） | 已能自动点弹窗「继续尝试」恢复；若仍停机**先查大麦待付款订单** |
| 时钟信任 severe | 设备/Mac 时钟未同步 | 同步时间后重跑 |
| CTA 文案护栏拦截 | 预约/预售态 | 属预期，开售后自动放行 |

## 文档索引

- 任务台账：[TASKS.md](TASKS.md)（E2E-01~17 全记录）
- 架构归档：[上游方法重构与坐标缓存](docs/architecture/上游方法重构与坐标缓存归档_2026-11-18.md)、[热路径提速实测](docs/architecture/热路径提速实测与GPT复验交接_2026-11-18.md)
- 真机方案：[大麦真机端到端脚本方案](docs/architecture/大麦真机端到端脚本方案_2026-11-18.md)、[HaTickets 真机接入](docs/architecture/HaTickets真机接入方案_2026-11-17.md)
- 新演出向导 skill：`.agents/skills/new-show-setup/SKILL.md`
