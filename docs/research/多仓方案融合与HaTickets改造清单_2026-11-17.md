# 多仓方案融合与 HaTickets 改造清单

更新：2026-11-17。决策：以 [HaTickets Mobile](https://github.com/currycan/HaTickets) 的真机 USB + uiautomator2 实现为**主代码基线**，在本项目内固定上游版本、运行基线、修改其模块；其他仓库提供可核查的页面定位、流程和产品设计参考。最终实现以本机真机页面样本和回归结果为准，不照搬任何仓库对速度、成功率或控件稳定性的宣称。历史参考仓库索引见[原调研](抢票参考仓库索引_2026-11-16.md)。

## 代码来源与取舍

| 来源 | 本项目采用的部分 | 需要改造或验证的部分 |
|---|---|
| [HaTickets](https://github.com/currycan/HaTickets/tree/master/mobile) | 直连真机、配置加载、状态探测、可停止运行、`--probe`/`--commit` 分级、单实例与提交记录，作为主骨架 | 先固定 commit 和许可证，按当前大麦 App 与真机 Android 版本跑上游基线；保留可追溯改动，再修选择器、页面分支和错误恢复。上游速度参数不直接视为适合本机。 |
| [WECENG/ticket-purchase](https://github.com/WECENG/ticket-purchase/tree/master/damai_appium) | 大麦 App 页面流程、资源 ID 和图片化票价时的索引选择思路；其 [V2 说明](https://github.com/WECENG/ticket-purchase/blob/master/damai_appium/app.md)明确票价 Text 可能为空 | 它使用 Appium；本项目先将有价值的定位和状态判断移到 u2 适配层，逐项对照真机 UI 树。资源 ID、坐标与等待时间均不保证当前版本可用。 |
| [Lzhimie/damai-ticket-helper](https://github.com/Lzhimie/damai-ticket-helper) | 大麦新版界面和场次、票档位置索引的候选做法 | 只作定位兜底参考；索引前必须核对演出、场次和价格，未核对时停止。图形界面不进入首轮热路径。 |
| [Pactum7/ticket-grabbing](https://github.com/Pactum7/ticket-grabbing/tree/main/MaoYan) | 猫眼的页面状态、票档、观演人与余票监测流程，供后续猫眼真机适配 | AutoX.js 运行方式与本项目不同；先提取流程和状态，重新在 u2 上实现并用猫眼真机样本验证。 |
| [Guyungy/damaihelper](https://github.com/Guyungy/damaihelper) | 后期任务启停、状态显示和日志界面的产品参考 | 可视化控制台后置；首轮先保证命令行真机流程正确。 |

## 本地改造模块与顺序

1. **基线可复现**：保存上游仓库 URL、commit、许可证、依赖锁定和原版 `--probe` 结果。将上游 checkout 与本项目改动分开，提交变更时注明来源和改动理由；第三方代码复用前核对许可证。
2. **设备层**：复用 HaTickets 的 u2 直连和设备选择；核对断线、锁屏、前台 App 切换。首轮只连一台实体 Android 手机。
3. **大麦定位层**：建立按当前 App 版本记录的选择器表。优先用可核查的文本/资源 ID；图片化信息采用“页面结构与位置索引 + 订单摘要复核”；OCR 仅在前两者不足时评估。每个选择器附脱敏样本和失效行为。
4. **流程层**：以 HaTickets 状态机为底，吸收 WECENG 的新版页面分支和预约/开售/缺货判断；每个状态限定允许动作。未知页、登录失效、验证页、价格不符和设备断线立即停止并记录原因。
5. **提交层**：保留 probe 与单次 commit 权限；在提交前核对演出、日期、票档、人数、观演人和金额。只允许一次目标订单提交；支付交由用户。
6. **猫眼适配层**：在大麦流程稳定后复用设备层、运行控制和记录能力，参考 Pactum7 的猫眼页面流程重新写适配器；不把大麦选择器和猫眼动作混用。
7. **可视化层**：CLI 流程验收后再考虑 GUI/控制台，参考 Lzhimie 和 Guyungy 的交互设计。

## 每项优化如何验收

建立“上游原版 → 本项目改版”对照台账：变更模块、对应页面样本、触发场景、修改前后结果和回退方式。优先修**正确性和可停止性**；只有在同一真机、同一页面、同一目标条件下确认没有误选/重复提交后，才比较耗时或调整刷新间隔。不能从仓库 README 的标称时间推断本机效果。

首轮验收依次为 USB 授权、上游只读基线、改版只读探测、提交前流程、用户监督下的单次提交。2026-11-18 USB 授权与大麦人工浏览已通过；上游源码下载、u2 探测、代码适配及真实下单仍未完成。接续编码见[Pi 交接](../architecture/Pi编码交接_2026-11-18.md)，具体进度以[任务清单](../../TASKS.md)为准。
