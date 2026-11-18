---
name: show-info-extract
description: 从大麦 App 当前页面提取演出基本信息（标题/场馆/场次/票档/状态）。用于新演出录入、回流蹲守配置（确定 price_index 与场次护栏文本）、信息核对。只读零点击，不触碰确定/提交。
---

# 演出信息提取 skill

> 使用方式与示例提示词见 [docs/AI助手配置.md](../../../docs/AI助手配置.md)。

## 何时用

- 录入新演出：需要知道场次列表、票档序号（price_index）、价格文本
- 配置回流蹲守：需要目标票档的 index + SKU 面板上的场次日期文本（护栏）
- 核对：预约/开售前后页面状态变化

## 如何提取

支持平台：大麦（`cn.damai`）与猫眼（`com.sankuai.movie`），按前台包名自动分流。

工具：`scripts/show_info.py`（只读：一次 `dump_hierarchy` + 纯解析，不发出任何点击）

```bash
# 1) 当前页面直接提取
.venv/bin/python scripts/show_info.py --serial <serial> --save-xml pagesamples/showinfo_<标签>.xml
```

输出 = 人读摘要 + JSON 块。解读要点：

- `state`：`detail_page`（详情页）/ `sku_page`（SKU 面板）/ `sku_page_sold_out`（全部缺货登记）/ `order_confirm_page`（订单页）/ `login_blocked`
- `sku_tiers`：票档数组，**index 就是 `--reflow-watch`/config 的 `price_index`**（顺序 = 面板从上到下）；`status`：`sold_out`（缺货登记等不可购词在卡内）/ `reservation`（可预约/预售）/ `unknown_or_available`
- `session_items`：场次项 bounds（**自绘无文本**，只能给坐标/序号）——序号就是 `--session-index`
- `session_candidates`：全页含 周X/日期 的文本（部分演出自绘，此列表可能为空）
- `cta.likely_active`：亮橙像素线索；`cta.blocked_text`：预约/未开售阻断词

## 两级面板（实测，2026-11-18 F✦FOREVER 上海场）

部分演出的 SKU 面板是**两级**结构：

```
第一级：场次列表（场次项自绘，无障碍树无文本，只能按 bounds 序号点）
第二级：票档列表（出现后才看得到 price flowlayout）
```

关键实测结论：

1. 面板刚打开时**只显示场次列表、无票档**；点选场次后才加载票档
2. **BACK 后重进面板不记得场次**，会回到场次列表——回流刷新必须重选场次（`reflow.prepare_tiers` 已实现）
3. 场次项**无任何文本**（日期/周几均不可读）——只能按序号点，选中项需看截图确认（橙色描边+橙字）
4. 面板底部 `¥0` + 确定 = 未选档；回流模式必须点票价再点确定（`--reflow-watch` 已自动关预选）
5. 缺货登记态票卡**有「缺货登记」文本**，在售票卡**无任何文本**（价格自绘）——回流触发=缺货登记消失

## 提取 SKU 面板（详情页看不到票档时）

详情页只有场次/价格区间，票档在 SKU 面板里。进入方式（**导航，不是购买**）：

```bash
# CTA 容器坐标从上一步 JSON 的 cta.container_bounds 取中心，shell tap 进入面板
# （必须用 show_info 提取的 bounds，不要凭记忆点）
.android-sdk/platform-tools/adb -s <serial> shell input tap <cx> <cy>
sleep 1.5
.venv/bin/python scripts/show_info.py --serial <serial> --save-xml pagesamples/showinfo_<标签>_sku.xml
# 提取完立刻返回详情页（面板上不点确定）
.android-sdk/platform-tools/adb -s <serial> shell input keyevent 4
```

红线：SKU 面板里**只 dump，不点确定/不点票档**（点票档会改变预选状态）。

## 回流蹲守配置（提取结果 → 命令）

```bash
.venv/bin/python scripts/e2e_run.py \
  --reflow-watch --submit \
  --show-tag <show_tag> --expected-total <金额> \
  --session-index <场次序号> --expect-session-date <2026.MM.DD> \
  --reflow-interval 2 --reflow-refresh 15 --reflow-max-minutes 300
```

1. **price_index**：目标票档在 `sku_tiers` 里的 `index`，写入 `config.local.jsonc`
2. **session_index**：两级面板必填，从 `session_items` 的 index 取（0-based，从上到下）；单级面板可省
3. **expect-session-date**：订单页场次护栏（如 `2026.11.21`）——订单页文本不含该日期就 STOP 不提交。这是两级面板防错场次的**最终防线**（场次项无文本，只能靠这一层验证）
4. **expected-total**：目标票档价格 × 张数（订单核对闸门用）
5. 刷新节奏：`--reflow-refresh 15` 表示每 15s BACK→CTA→重选场次→看缺货登记是否消失（库存不自动刷新，刷新节奏≈发现延迟）；实测每轮开销 ~5s
6. 回流模式自动关闭预选（面板未选档，必须点票价）

安全：触发后仍走完整闸门（订单金额+场次日期+观演人核对→提交前弹窗筛查→提交→只读验证），任一不过就停机。

## 安全边界

- 本 skill 全程只读 + 导航级点击（CTA/BACK），不点确定、不提交
- 提取的 XML 存 `pagesamples/`（gitignored）
- 若 `state=login_blocked`：先人工登录再提取
