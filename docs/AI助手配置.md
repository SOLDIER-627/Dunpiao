# 用 AI 助手配置（Skill 使用指南）

本仓库自带两个 **Agent Skill**，交给多模态 AI 助手（Claude Code / pi / Cursor 等支持
`SKILL.md` 约定的编码助手）使用：你只管连好 USB、把手机停在大麦 App 的演出详情页，
剩下的**读页面、认场次、认票档、写配置**由 AI 完成，你只负责逐项确认。

```
.agents/skills/show-info-extract/SKILL.md   提取当前页信息（只读）
.agents/skills/new-show-setup/SKILL.md      新演出录入：采集 → 确认 → 写配置
```

两个 skill 都是**只读采集 + 人工确认**，不点确定、不提交、不碰支付。

---

## 准备（一次性）

1. Mac 连好安卓手机，USB 调试已授权：`.android-sdk/platform-tools/adb devices` 能看到设备
2. `.venv/bin/python` 可用（3.12 + uiautomator2）
3. 大麦 App 已登录，**实名观演人已在 App 内配好**（脚本只勾选、不新增）
4. 手机停在大麦 App 里**目标演出的详情页**（能看到「立即购票」按钮那一页）
5. 系统动画三档缩放 = 0（开发者选项）

> 手机停在 SKU 面板（场次/票档选择层）也可以——skill 会自己判断当前在哪一层。

---

## 用法一：录入新演出（推荐流程）

在 AI 助手里直接说人话即可。示例提示词：

### 示例 1：标准录入（信息齐全）

```
帮我配置一个新演出。
手机已连好，大麦 App 停在目标演出详情页。

目标：11.21 周六场，看台 588 这一档。

请用 new-show-setup skill：
1. 先 capture 采集
2. 把采集到的标题/场馆/场次/票档逐项列出来跟我确认
3. 我确认后再 apply 写配置，show_tag 用 forever_588_20261121
```

### 示例 2：我不确定场次/票档序号，让 AI 自己查

```
大麦停在详情页了，我要抢「F✦FOREVER 上海」周六那场，看台 488。

用 show-info-extract skill 先提取页面信息，如果当前页看不到票档，
你自己点进 SKU 面板提取（只点导航，别点确定），提取完退回来。
然后告诉我：周六是第几个场次（session_index）、看台 488 是第几个票档
（price_index），再按 new-show-setup 的流程写配置。
```

### 示例 3：多场次演出（skill 会强制逐场采集）

```
这个演出有周五/周六/周日三场，我只蹲周六 18:30 的看台 488。

按 new-show-setup 的规则来：每个场次单独采集一次，别用上一场的数据推断。
采集完给我一张对照表（场次 / 票档数 / 在售数 / 目标档状态），我确认后再写配置。
```

---

## 用法二：只提取信息（不改配置）

```
手机停在大麦某个演出页，用 show-info-extract skill 提取一下：
标题、场馆、场次、票档列表和各自状态（在售/缺货登记），
顺便告诉我如果要蹲「周六 看台488」该填什么 session_index 和 price_index。
```

AI 会跑 `scripts/show_info.py`（一次 dump + 纯解析，零点击）并给结论：

```
页面状态 : sku_page（NcovSkuActivity）
场次项   : [0] [63,712][1137,883] | [1] [63,883][1137,1054] | [2] ...
票档列表 :
  [0] sold_out            bounds=[63,554][520,725]  texts=['缺货登记']
  [1] sold_out            bounds=[63,725][772,896]  texts=['缺货登记']
  [2] unknown_or_available bounds=[63,896][402,1067] texts=[]
  ...
```

> `sold_out` = 卡内有「缺货登记」；`unknown_or_available` = 卡内无任何文本（价格自绘）
> 通常就是在售。**票档序号（index）就是 `price_index`；场次序号就是 `session_index`。**

---

## 用法三：配置回流蹲守

```
周六看台 488 现在缺货登记，帮我配回流蹲守。

用 show-info-extract 确认 488 的 price_index 和周六的 session_index，
然后给我一条可以直接跑的 reflow.py 命令（含 --expect-session-date），
先不要加 --submit，我要先看一遍。
```

AI 会给出类似：

```bash
.venv/bin/python scripts/reflow.py \
  --show-tag forever_488_20261121 --expected-total 488.00 \
  --session-index 1 --expect-session-date 2026.11.21 \
  --reflow-interval 2 --reflow-refresh 15 --reflow-max-minutes 300
```

---

## AI 会做什么 / 不会做什么

| 会做 | 不会做 |
|---|---|
| 读 `dump_hierarchy`、截图（多模态看自绘区域） | 点「确定」「立即提交」 |
| 点 CTA 进入 SKU 面板、BACK 返回（仅导航） | 改实名观演人、加观演人 |
| 逐项列字段跟你确认 | 跳过确认直接写配置 |
| 写 `config.local.jsonc` 的白名单字段 | 把敏感信息（姓名/手机号/序列号）写进仓库或对话 |
| 给可直接复制的运行命令 | 自动付款 |

配置写入只覆盖白名单字段：`keyword` / `date` / `price` / `price_index` /
`session_index` / `target_title` / `target_venue`。`users`（观演人）等敏感字段永不自动改。

---

## 常见问题

| 现象 | 原因 / 处置 |
|---|---|
| AI 说「不在详情页」 | 手机不在大麦演出详情页；手动打开后再让它采集 |
| 场次项 `texts=[]` 且没有日期 | 该演出场次自绘（qilin 座席版），只能按序号点 → 用 `--session-index` |
| 票档 `texts=[]` 却不是在售 | 页面还在加载；等 1-2 秒重新提取 |
| 提取到的价格区间和票档对不上 | 详情页价格是区间（¥488-1688），票档要进 SKU 面板才有 |
| 预约（未开售）态票档只有「可预约」 | 预约态无价格文本，`price_index` 只能人工指认；开售后以重测+文本匹配为准 |

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
