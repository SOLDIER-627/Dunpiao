# Pi 编码交接（2026-11-18）

更新：2026-11-18。本文是**下一阶段编码工作的交接与执行说明**：主线已从调研/方案阶段进入编码阶段，由 Pi（编码助手）接手，覆盖 [TASKS](../../TASKS.md) 的 PH-02 收尾至 PH-05。技术依据见[真机方案](HaTickets真机接入方案_2026-11-17.md)、[多仓融合清单](../research/多仓方案融合与HaTickets改造清单_2026-11-17.md)、[上游核查](../research/HaTickets真机路线核查_2026-11-17.md)。

## 一、一句话现状

**大麦 App + 用户实体 Xiaomi 14（Android 16，大麦 9.0.38.6）+ Mac USB + Python uiautomator2 直连**；主代码基线为 HaTickets Mobile（u2 直连路线）。PH-00/PH-01 已通过（USB 授权成功，`adb devices` 单台 `device`，大麦人工浏览正常）；**PH-02 进行中**：隔离环境已就绪，HaTickets 上游源码尚未取得（GitHub 直连超时）。

## 二、环境快照（2026-11-18 已验证事实）

| 项 | 状态 |
|---|---|
| Python 隔离环境 | `.venv` = Python **3.12.14**（满足上游 `<3.14` 约束） |
| 关键依赖 | `uiautomator2 3.7.1`、`adbutils 2.12.0`、`pillow 13.0.0`（暂无 opencv，OCR 阶段再评估） |
| ADB | `.android-sdk/platform-tools/adb`（1.0.41，官方 Platform-Tools） |
| 设备 | 实体 Xiaomi 14 / Android 16 / 大麦 9.0.38.6，单台 `device`（序列号不进文档与聊天） |
| 目录 | `pagesamples/`（脱敏截图）、`logs/`（运行日志）、`scripts/diagnose_android_login.py`（只读环境摘要） |
| 配置 | `config.example.yaml` 是本项目设计模板；运行上游 HaTickets 需另复制其 `mobile/config.example.jsonc`（双轨，勿混用） |
| HaTickets 源码 | **未取得**（PH-02 剩余事项） |

## 三、代码路线

### 主代码基线

以 [currycan/HaTickets](https://github.com/currycan/HaTickets) `master` 的 `mobile/` 为主骨架（Apache-2.0）：u2 直连、设备序列号选择、`--probe`/`--commit` 权限分级、状态探测、单实例锁、提交记录。**固定 commit 后再改造**，上游 checkout 与本项目改动分开存放，每项改动在对照台账登记来源与理由。

### 来源分工（详见[融合清单](../research/多仓方案融合与HaTickets改造清单_2026-11-17.md)）

| 来源 | 采用 | 用途 |
|---|---|---|
| HaTickets | 直连/配置/状态机/可停止/闸门 | 主骨架 |
| WECENG/ticket-purchase | 资源 ID、图片化票价索引选择 | 大麦定位层参考（Appium→u2 移植） |
| Lzhimie/damai-ticket-helper | 新版界面、场次/票档索引兜底 | 定位兜底（索引前必须复核） |
| Pactum7/ticket-grabbing | 猫眼页面流程 | MY-PH 猫眼适配（流程提取，非代码照搬） |
| Guyungy/damaihelper | 启停/状态/日志界面 | UX-PH 可视化后置 |

### 分层结构（改造顺序即融合清单 1→7）

基线可复现 → 设备层（u2 直连/断线/锁屏/前台）→ 大麦定位层（选择器表+样本+失效行为）→ 流程层（状态机+限定动作+安全停止）→ 提交层（probe/单次 commit+五要素核对）→ 猫眼适配层 → 可视化层。首轮只连一台实体机，不装 Appium/AutoX，scrcpy 后置。

### 热路径情报索引（PH-05 之后再启用）

实现到热路径时查[参考仓库索引](../research/抢票参考仓库索引_2026-11-16.md)第三节收敛结论：大麦官方对时接口（NNBS）+ monotonic 锚定（HaTickets clock_sync）、0 秒抖动 ~500ms、"预选"压缩热路径为 3 步、快速重试 80ms×8、坐标缓存。**速度优化在正确性验收之后**，上游标称耗时不可照搬。

## 四、交接任务与验收（按顺序执行）

### PH-02 收尾：取得并固定 HaTickets 基线（当前最优先）

1. 获取源码。GitHub 网页直连曾超时，但 `api.github.com` 可达（历轮调研实测）——优先 `https://api.github.com/repos/currycan/HaTickets/zipball/<commit>` 或 `git clone https://github.com/currycan/HaTickets.git` 重试；**不要使用不可信第三方镜像**。
2. 固定当时 `master` HEAD commit，记录到台账；确认 LICENSE = Apache-2.0，`pyproject.toml` 约束（Python `<3.14`、`uiautomator2` 版本）与本机 `.venv` 兼容；若上游 pin 的 u2 版本与已装 3.7.1 冲突，记录差异并按上游锁定（基线阶段以上游为准）。
3. 上游目录建议放 `reference/HaTickets@<commit>/`（只读参考 + 原版运行）；本项目改造代码放独立目录，不混写。
4. 复制 `mobile/config.example.jsonc` → 本地 `config.jsonc`（加入 .gitignore），只填脱敏可运行的最小配置（`--probe` 需要 serial/目标演出；真实姓名、序列号不进仓库）。
5. 验收：上游原版在 `.venv` 中可导入运行（不连设备也能 `--help`/载入配置）；commit、许可证、依赖锁定已记录。

### PH-03：只读探测对照（上游原版 vs 本项目改版）

- 用户手动打开精确目标（非热门演出）详情页；先跑上游 `--probe`，再跑本项目探针，记录差异。
- **预期失败点**：Xiaomi 14 / Android 16 / 大麦 9.0.38.6 超出上游推荐（Android 12–14），上游已有 issue #41（Android 16 复现与控件失效）、#61（搜索/票档失效）——控件失效是预期现象，**记录而非硬修**，作为 PH-04 改造输入。
- 验收：两版结果与差异有台账记录；正确识别演出与页面状态；停在购票入口前；无任何提交。
- 注意：u2 辅助组件是新的暴露面（此前只有 ADB）；探针后人工操作大麦确认登录态无异常，异常则记录时间与报错并停止。

### PH-04：定位层与流程层融合改造

- 按真机页面样本（`pagesamples/`）建立本项目选择器表：优先文本/资源 ID；票价图片化 → 容器 + `price_index`（必选路径，参考 WECENG v2）；OCR 仅评估。
- 状态机以 HaTickets 为底，吸收 WECENG 新版页面分支与预约/开售/缺货判断；未知页、登录失效、验证页、价格不符、断线 → 立即停止并记录。
- 每项改动登记：变更模块、页面样本、触发场景、前后结果、回退方式。正确性与可停止性优先于速度。

### PH-05：单次人工监督提交（独立验收）

- 仅在用户明确目标场次后运行；`--commit` 单次进程授权；提交前核对演出、日期、票档、人数、观演人、金额；最多创建一张目标订单；检测到待支付立即停，**支付由用户本人完成**。

## 五、约束与红线（全程有效）

- 手机不动：不 root、不刷机、不重装大麦、不清数据、不导出会话；USB 授权异常交用户处理，不绕过。
- 敏感信息（账号、观演人真实姓名、设备序列号、验证码）不进 git、不进聊天、不进截图分享；`config.jsonc`/`config.local.yaml` 忽略。
- probe 与 commit 权限分离；验证码/滑块由用户人工处理，不做代解；不做签名逆向、接口直调、代理池、自动支付。
- 不高频重试页面操作；出现验证/拒绝 → 暂停交人工。
- 工作区 git：编码阶段由 Pi 正常提交（信息注明来源与理由）；Dunpiao 归档仓照旧单向同步，敏感与账号相关内容不入归档。

## 六、已知坑（执行时注意）

1. **GitHub 直连超时**：用 `api.github.com`/zipball 路径取源码；失败时先查代理与 DNS，不换不可信镜像。
2. **Android 16 兼容**：系统版本 + App 版本双变量，兼容性问题勿只归因于系统；所有探测结果先记录。
3. **u2 组件暴露面**：`com.github.uiautomator`/atx-agent 会在设备上安装服务；首轮探针后验证大麦人工使用无异常；用完可 `adb uninstall com.github.uiautomator`（热路径阶段再装回）。
4. **双配置轨**：本项目 `config.example.yaml`（设计模板）≠ 上游 `config.jsonc`（运行必需），运行上游时只复制上游模板。
5. **上游文档混杂**：HaTickets 文档含旧 Appium/WebDriver 段落，以当前 `mobile/` 代码与 README 三旗标语义（`--probe`/`--commit`/`--yes`）为准。
6. **速度宣传不可信**：所有仓库的耗时/成功率为标称值，本机效果以对照台账实测为准。
