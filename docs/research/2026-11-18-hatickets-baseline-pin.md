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

## 开票中页面对照（2026-11-18 10:05-10:07，李大奔 BENZO 场）

### 本轮最重要的技术发现：CTA 无障碍不可见

开票中的详情页实测——购票按钮**视觉上已渲染**（容器区域像素均值 RGB(235,116,59)，即大麦橙按钮色），但：

- `dump_hierarchy` 抓不到（容器节点 0 子节点）
- u2 选择器跨窗口查询也查不到（textMatches/descriptionMatches/resourceId 全部 count=0）
- 原因（dumpsys window 实证）：购票栏渲染在 `BricksChannelPageActivity` 动态模板窗口（Window #11），与详情主窗口（ProjectDetailActivity，Window #10）分离，无障碍树不暴露其节点

**推论（进 DM-04 设计基线）**：大麦购票核心 UI 疑似故意不暴露无障碍节点（反自动化）。生态三阶梯中"资源 ID/文本匹配"对**详情页 CTA** 在本版本基本失效；唯一可行路径 = **容器 bounds 坐标锚定点击**（上游做法，容器位置稳定）+ 像素/OCR 验证辅助。票档页（SKU）按钮是否同样不可见，待真实 SKU 样本验证。

### 对照结果（配置修正后）

| 维度 | 上游原版 | 改版探针 v1（+像素验证） |
|---|---|---|
| 目标校验 | **不匹配即拒绝**（荔枝场配置未改时正确拒绝探测李大奔页）✅ 安全行为 | 无目标校验（只报状态，防抢错场逻辑在流程层实现） |
| 页面/就绪 | detail_page，ready=true，0.60s，exit=0 | detail_page + 全量结构化信息（标题/场次 11.28 19:00/价格 ¥380-980） |
| CTA | 容器级就绪 | 容器 empty + **button_visually_rendered=true**（像素判定） |
| 预选横幅 | 未检测 | 检出"预选本次实名抢票观演人，抢票快人一步！" |

改版探针已升级：`container_bounds` 记录、`pixel_check_cta()` 容器区域均值色启发式（橙红判定）、警告文案修正。日志：`logs/probe_upstream_onsale2_2026-11-18.log`、`logs/probe_v2_onsale2_2026-11-18.json`；样本：`pagesamples/onsale2_2026-11-18.xml`。

## SKU 页（售罄态）对照（2026-11-18 10:08-10:09，李大奔 BENZO 场）

样本：`pagesamples/sku_100836.xml` + `sku_screen_*.png`（活动 `NcovSkuActivity`）。该场开票后全部票档进入缺货登记，恰好提供**售罄态 SKU 完整样本**（回流票监控 P4 的目标状态实证）。

### 关键发现

1. **票价文本彻底不在无障碍树**：票档容器内只有 4 个 `tv_tag='缺货登记'`，价格连空 TextView 都没有——比 WECENG"text 为空串"的结论更彻底，价格是纯动态模板渲染。"容器 + 索引 + 像素/OCR"成为唯一路径（三阶梯收敛为单路径）。
2. **票档条目结构**：容器 `project_detail_perform_price_flowlayout` 内 5 个 clickable 无名 FrameLayout，bounds 完整可得 → **索引定位 + 坐标点击可行**（本机 5 档、bounds 无重叠）。
3. **btn_buy_view 同样无障碍不可见**：有节点、无 text/desc、无子节点、clickable=false；像素实证视觉存在——**置灰态 ≈ RGB(241,176,132)**，可购态 ≈ (235,116,59)。像素启发式已放宽覆盖置灰态，且两态色差可判按钮可用性（后续做可购/置灰二分类）。
4. **观演人/数量区域未渲染**（售罄态无该区域）——有票态样本待真实可购场次补充；`layout_num`/`img_jia`/观演人选择器沿用上游/WECENG，待验证。
5. **上游盲区实证**：上游正确识别 sku_page 但因目标校验依赖详情页标题（SKU 页头标题 ID 不同）拒绝继续；改版探针作为纯状态分类器成功分类 `sku_page`（升级：活动名感知 + 票档结构识别 + 售罄态判定 + 置灰像素启发式）。

### 状态分类器 v1 现状

`detail_page` / `detail_page`（CTA 两级就绪 + 像素验证）/ `sku_page` / `sku_page_sold_out` / `login_blocked` / `order_confirm_page`（文本粗判）/ `unknown_or_other`。对照记录：`logs/probe_upstream_sku_2026-11-18.log`、`logs/probe_v2_sku_2026-11-18.json`。
