---
name: new-show-setup
description: Configure dunpiao for a new Damai show (新演出预检). Use when the user wants to set up a new target show, confirm show/session/tier info, or update config for a different performance. Guides read-only capture from the phone, AI-assisted confirmation of every field with the user, and safe config writing.
---

# 新演出 AI 化确认（dunpiao 新演出预检向导）

工具：`src/dunpiao/show_wizard.py`。两步模式：**capture（只读）→ AI 与用户逐项确认 → apply（写配置）**。
你（AI 助手）就是"确认层"：把采集结果逐项展示给用户，用户确认后才写入。

## 第一步：capture（只读，零点击）

要求用户把手机停在大麦 App 目标演出的**详情页**，然后运行：

```bash
cd /Users/Admin/Desktop/work/Ticket
.venv/bin/python -m src.dunpiao.show_wizard capture
```

输出 JSON（同时存档到 `logs/shows/capture_*.json`）。不在详情页会退出码 2 并提示。

## 第二步：AI 逐项确认（在对话中完成，不得跳过）

把 capture JSON 的以下字段**逐项**列给用户确认，每项都要用户明确答复（是/否/更正）：

1. **title** 演出标题 —— 是否目标演出
2. **venue** 场馆 + **show_time** 场次时间 —— 是否目标场次
3. **tiers_total / tiers_available** 票档数与在售数 —— 是否符合用户预期
4. **price_range** 价格区间 —— 目标票档是否在其中

### 多场次演出（关键规则）

同一演出多个场次时：**每个场次单独 capture 一次**。让用户在手机上切换到
下一个场次（详情页内切换，不换页面），重新运行 capture，对比两次的
`show_time` 与 `tiers_*` 是否不同（实测踩坑：切换场次后票档数与在售状态
会变，严禁用上一场次的票档信息推断下一场次）。

## 第三步：apply（用户全部确认后才允许执行）

确定 show_tag（格式建议 `<拼音或英文名>_<价格>_<日期YYYYMMDD>`，如
`libenben_780_20261128`），然后：

```bash
.venv/bin/python -m src.dunpiao.show_wizard apply --tag <show_tag> \
  --keyword "<搜索关键词，如 李大奔>" \
  --date "<与详情页场次时间可匹配的子串，如 11月28日 周六>" \
  --price "<目标票档价格数字，如 380>" \
  --price-index <该票档在容器中的序号，0-based，数 capture JSON 的 tier_bounds> \
  --title "<演出标题>" --venue "<场馆>"
```

- `--price-index`：capture JSON 的 `tier_bounds` 是容器内顺序；目标票档是第几个（0 起）。
  若该档当前"缺货登记"，如实标注——apply 照常写，但提醒用户该档目前不可购。
- apply 只覆盖白名单字段（keyword/date/price/price_index/target_title/target_venue），
  **永不触碰 users（观演人）等敏感字段**；找不到键会拒绝而非静默新增。

## 红线（必须遵守）

- capture 全程零点击；任何验证/风控弹窗出现 → 停止，交人工
- **档案不存坐标**：坐标一律运行时重新定位（开票后布局会变）——
  不要把 tier_bounds 当作可复用的点击坐标，它只用于序号确认
- 敏感信息（账号/观演人/设备序列号）不进 git、不进对话、不进截图
- `logs/shows/`、`config.local.jsonc` 均 gitignored，档案与配置不入库
- 完成后提醒用户：跑一次 `scripts/e2e_run.py`（无提交）验证新配置端到端可用
