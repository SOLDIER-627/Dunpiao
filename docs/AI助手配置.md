# 用 AI 助手配置（Skill 使用指南）

本仓库自带两个 Agent Skill，交给多模态 AI 助手（Claude Code / pi / Cursor 等支持
`SKILL.md` 的编码助手）使用：你连好 USB、把手机停在大麦演出详情页，剩下的
**读页面、认场次、认票档、写配置**由 AI 完成，你只负责确认。

```
.agents/skills/show-info-extract/SKILL.md   提取当前页信息（只读）
.agents/skills/new-show-setup/SKILL.md      新演出录入：采集 → 确认 → 写配置
```

两个 skill 都是**只读采集 + 人工确认**：不点确定、不提交、不碰支付、不改观演人。

---

## 前置准备

### 1. 硬件与系统

- Mac 用 USB 连安卓手机，手机开启**开发者选项 → USB 调试**，并在弹窗里**允许该电脑调试**
- 手机端**系统动画三档缩放设为 0**（开发者选项里三项：窗口/过渡/动画时长程序），热路径依赖这一点
- 手机保持**解锁**状态（锁屏会让脚本找不到页面）

### 2. 检查连接

```bash
# 应列出你的设备（unauthorized 表示还没在手机上点「允许」）
.android-sdk/platform-tools/adb devices
```

### 3. Python 环境

```bash
.venv/bin/python -V        # 3.12
.venv/bin/python -c "import uiautomator2; print('u2 ok')"
```

设备端 uiautomator server 首次连接会自动安装（需要几秒）。

### 4. 大麦 App

- 已登录（登录过期会在页面上提示，脚本会 STOP）
- **实名观演人已在 App 内配置好**——脚本只勾选，不会新增或修改
- 打开到**目标演出的详情页**（大麦或猫眼都可以，能看到底部「立即购票 / 已预约」那一页）

### 5. 配置文件

```bash
cp config.example.jsonc config.local.jsonc   # 首次
```

`config.local.jsonc` 已 gitignored，**不入库、不进对话**。里面至少要填对
`users`（观演人姓名，订单核对用）——这一步人工填，不要交给 AI。

---

## 支持平台

`scripts/show_info.py` 按前台包名自动分流，两个平台都能提取：

| 平台 | 包名 | 能提取 |
|---|---|---|
| 大麦 | `cn.damai` | 标题/场馆/场次/票档/CTA/场次项/预约标记 |
| 猫眼 | `com.sankuai.movie` | 标题/场馆/场次/票档/CTA/订单页金额与提交按钮 |

## 示例提示词

只记两条，按模式选一条。

### 抢票（开售准点）

```
手机已连好，大麦停在目标演出详情页。帮我配抢票：11.21 周六场，看台 588。
用 skill 提取信息，跟我确认后写配置。
```

### 回流（缺货登记蹲守）

```
手机已连好，大麦停在该演出页。帮我配回流蹲守：周六场，看台 488（现在是缺货登记）。
用 skill 确认场次和票档序号，然后给我一条可以直接跑的 reflow.py 命令。
```

AI 会依次：提取页面（必要时点进 SKU 面板，只点导航）→ 列出标题/场馆/场次/票档
逐项跟你确认 → 写 `config.local.jsonc` → 给出可直接复制的运行命令。

---

## AI 会做什么 / 不会做什么

| 会做 | 不会做 |
|---|---|
| 读 `dump_hierarchy`、截图（多模态看自绘区域） | 点「确定」「立即提交」 |
| 点 CTA 进 SKU 面板、BACK 返回（仅导航） | 改/加实名观演人 |
| 逐项列字段跟你确认 | 跳过确认直接写配置 |
| 写 `config.local.jsonc` 白名单字段 | 把姓名/手机号/序列号写进仓库或对话 |
| 给可直接复制的运行命令 | 自动付款 |

配置只覆盖白名单字段：`keyword` / `date` / `price` / `price_index` /
`session_index` / `target_title` / `target_venue`；`users` 永不自动改。

---

## 常见问题

| 现象 | 原因 / 处置 |
|---|---|
| AI 说「不在详情页」 | 手机不在大麦演出详情页，或已锁屏；手动打开后再采集 |
| 场次项没有日期文本 | 该演出场次自绘（qilin 座席版），只能按序号 → 用 `--session-index` |
| 票档 `texts=[]` 却不是在售 | 页面还在加载；等 1-2 秒重新提取 |
| 详情页价格区间 ≠ 票档 | 详情页是区间（¥488-1688），票档要进 SKU 面板才有 |
| 预约态票档只有「可预约」 | 预约态无价格文本，`price_index` 只能人工指认；开售后以重测+文本匹配为准 |

---

## 手动等价命令（不想用 AI 时）

```bash
# 提取当前页信息（只读）
.venv/bin/python scripts/show_info.py --serial <serial> --save-xml /tmp/page.xml

# 新演出采集（只读）→ 人工确认 → 写配置
.venv/bin/python -m src.dunpiao.show_wizard capture
.venv/bin/python -m src.dunpiao.show_wizard apply --tag <tag> \
  --keyword "<关键词>" --date "<日期子串>" --price "<价格>" \
  --price-index <序号> --title "<标题>" --venue "<场馆>"
```
