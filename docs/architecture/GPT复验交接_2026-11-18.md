# GPT 复验交接 — PH-04/PH-05 结论独立复核（2026-11-18）

> 写给：GPT（负责 computer use 与安卓环境的并行助手）
> 写者：Claude（Pi 会话）
> 目的：Claude 在 2026-11-18 完成了 PH-04（选择器/状态分类）与 PH-05（全流程实测），请你**独立复核**以下结论是否可复现，重点是用你侧的视角（computer use 截图/人工操作对照）交叉验证自动化探针的判定。
> 红线不变：无验证码代解、无注入框架、无接口直调、无自动支付；出现滑块/拒绝即暂停交人工。

## 1. 环境快照（复核前提）

| 项 | 值 |
|---|---|
| 项目根 | `/Users/Admin/Desktop/work/Ticket` |
| Python | `.venv/bin/python`（3.12.14；uiautomator2 3.7.1、adbutils 2.12.0、pillow） |
| adb | `.android-sdk/platform-tools/adb` |
| 设备 | 用户实体 Xiaomi 14（Android 16 / HyperOS / 大麦 9.0.38.6），USB 连接 |
| 设备序列号 | 存于 `/tmp/.hat_serial`（**日志/文档中一律脱敏为 SERIAL**） |
| 上游基线 | `reference/HaTickets/`（只读，commit `76946bf`），入口 `cd reference/HaTickets/mobile && PYTHONPATH=. python -m damai_app --help` |
| 本项目探针 | `.venv/bin/python -m src.dunpiao.probe [--serial S] [--json F] [--save-xml F]` |
| 配置 | `config.local.jsonc`（gitignored；含观演人姓名，输出一律脱敏） |
| 关键设备设置 | 开发者选项 → **USB 调试（安全设置）已开启**（2026-11-18，用户操作；见 §4 环境发现 #1） |

## 2. Claude 已验证的结论（待你复核）

### PH-04：页面状态分类与选择器

| # | 结论 | 复核方法 |
|---|---|---|
| C1 | 详情页 CTA（购票按钮）**不在无障碍树**：渲染在 `BricksChannelPageActivity` 动态模板窗口；`dump_hierarchy` 与 u2 选择器均查不到，但按钮视觉存在 | 在任一在售/预售演出详情页跑探针 `--json`，看 `cta.container_empty=true`；同时用你侧截图人工确认按钮在屏幕上 |
| C2 | CTA 像素判活：可购态橙 ≈ RGB(235,116,59)，缺货置灰 ≈ (241,176,132)，SKU 选中票档后 ≈ (236,127,67) | 截图后用 PIL 算容器区域均值（方法见 `src/dunpiao/probe.py: pixel_check_cta`） |
| C3 | SKU 页票价文本**完全不在无障碍树**（连空 TextView 都没有，只有 `tv_tag`）；票档 = 容器内 clickable 无名 FrameLayout，bounds 可得；**无"缺货登记"标签的档 = 在售档** | 在 SKU 页 dump，数票档数 vs 缺货标签数，与屏幕对照 |
| C4 | SKU 页**两步制**：点票档仅选中，还需点 `btn_buy_view`（[约 726,2514][1137,2646]）才进订单页 | 人工走一遍（或让用户操作），对照 `pagesamples/ph05_*.xml` |
| C5 | 订单确认页（`DmOrderActivity`）是原生 UI：`立即提交` TextView 可见可点击；观演人姓名、`×N张`、`¥ 总价` 均为可读文本 | 到订单页跑探针，看 `order` 字段；与屏幕对照 |
| C6 | 状态分类器全景：`login_blocked / detail_page / sku_page / sku_page_sold_out / order_confirm_page / unknown_or_other` | 各页面各跑一次探针核对 state |

### PH-05：全流程实测（已走通一次）

- 路径：详情页 →（CTA 坐标点击）→ SKU 页 →（在售票档 + 确认按钮）→ 订单页 →（机读核对 + 单次点击『立即提交』）→ **支付宝收银台（`MspContainerActivity`）停止**，付款交人工
- 证据：`logs/ph05_20261118_101416/`（逐步截图 + XML + run.log）
- 提交 → 收银台 ~3 秒（含固定 sleep）；热路径预估 <2s（未实测）
- **注意**：复验时每点一次『立即提交』都会创建真实预售订单（未付款会超时自动取消）。**建议复验只做到订单页核对为止，不要再点提交**——除非用户明确再次授权

## 3. 你侧复验清单（建议顺序）

1. **零成本核对**：读 `logs/ph05_20261118_101416/` 的截图与 run.log，对照本表 C1–C6，标记任何与你在真机上见过的不一致
2. **探针复跑**（只读、零点击）：详情页 / SKU 页各跑 `probe --json`，核对 state 与字段；`pagesamples/` 有全部原始 XML 可比
3. **人工操作对照**：请用户配合在详情页人工点击购票 → 选票档 → 确认 → 订单页（**不点提交**），你逐步截图，与探针判定逐项对照
4. **上游基线复跑**（只读 probe）：`cd reference/HaTickets/mobile && PYTHONPATH=. HATICKETS_CONFIG_PATH=<config.local.jsonc> ../../.venv/bin/python -m damai_app --serial $(cat /tmp/.hat_serial)`——预期 detail_page ready=true（注意其就绪是**容器级**，与 C1 不矛盾）
5. 输出：复验报告（逐条 ✅/❌/偏差说明），写回 `docs/research/` 下新文件

## 4. 已知坑（务必先读）

1. **HyperOS 输入注入加固**：u2 的 `d.click()`（UiAutomation 注入）与 `adb shell input tap` 在默认设置下**都被系统拒绝**（INJECT_EVENTS SecurityException）；必须开启「USB 调试（安全设置）」后 shell 层注入才可用。**复验若需点击，确认该设置仍开启**；只读操作不受影响
2. **探针订单页判定勿裸匹配 "order"**：详情页 activity 路径含 `newtradeorder`，会假阳性（已修为匹配类名前缀 `dmorder`）
3. **上游"就绪"是容器级**：`--probe` 的 ready=true 只代表 CTA 容器有 bounds，不代表按钮无障碍可见（C1）
4. **双配置轨**：本项目 `config.local.jsonc` ≠ 上游 `config.jsonc`；上游入口必须在 `reference/HaTickets/mobile/` 目录下运行
5. **速度宣传不可信**：所有标称耗时以本机实测为准
6. **敏感信息**：观演人姓名、手机号、设备序列号不进 git、不进聊天、不进截图说明文字；`config.local.jsonc`/`logs/`/`pagesamples/` 已 gitignored，但**引用样本内容时仍需脱敏**

## 5. 文件索引

- 台账（全部结论与证据链）：`docs/research/HaTickets基线固定_2026-11-18.md`
- 探针：`src/dunpiao/probe.py`、`src/dunpiao/selectors.py`
- PH-05 步进脚本：`scripts/ph05_flow.py`（s1/s2/s3 三步，各自带核验闸门）
- 页面样本：`pagesamples/`（detail_*.xml 预约态、onsale*.xml 开票态、sku_*.xml 售罄+在售混合态、sku780_*.xml 订单页、ph05_*.xml 全流程逐步）
- 参考仓库索引：`docs/research/抢票参考仓库索引_2026-11-16.md`
- Pi 编码交接（背景）：`docs/architecture/Pi编码交接_2026-11-18.md`

## 6. 待办边界（你复验之后的事）

- P3：开票瞬间 0 秒抖动实测（需真实开票场次，勿用预售单模拟）
- P4：回流票时间窗监测（SKU 售罄态探针已是雏形）
- MY-PH：猫眼适配前需先调研猫眼等价情报（对时接口 / 0 秒行为 / 资源 ID）
- 以上均不在本次复验范围内
