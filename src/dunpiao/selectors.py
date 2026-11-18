# -*- coding: utf-8 -*-
"""大麦 App 选择器表（本项目改版定位层 v1）。

来源标注：
  [U]  HaTickets 76946bf page_probe.py 常量（上游基线）
  [W]  WECENG/ticket-purchase damai_app_v2.py（Appium 侧实证，移植到 u2）
  [N]  NNBS / 生态调研（8.x 时代，仅作历史互证）
  [L]  本机样本 pagesamples/detail_*.xml（Xiaomi 14 / Android 16 / 大麦 9.0.38.6，
       2026-11-18 预约阶段详情页实测）

纪律：
  1. 优先资源 ID > 文本 > 位置索引；票档图片化（text 为空）时必须走容器+索引，
     索引使用前必须与订单摘要复核（融合清单第 3 条）。
  2. 每个选择器附失效表现；探针只读，任何状态下不点击。
  3. 选择器表只记录"在哪找"，判定语义在 probe.py 的状态机里。
"""

# --- 详情页（detail page） ----------------------------------------------------

TITLE_IDS = (
    "cn.damai:id/project_title_tv1",   # [U][L] 实测 text=演出全名
    "cn.damai:id/project_title_tv2",   # [U]
    "cn.damai:id/title_tv",            # [U]
)

VENUE_IDS = (
    "cn.damai:id/venue_name_0",        # [U][L] 实测 "上海市 · 虹口足球场"
    "cn.damai:id/tv_project_venueName",  # [U]
)

SHOW_TIME_IDS = (
    "cn.damai:id/tv_show_time",        # [L] 实测 "2026.12.05 周六 19:00"（上游常量表未见，本机新增）
)

PRICE_LAYOUT_IDS = (
    "cn.damai:id/project_detail_price_layout",  # [U][L]
    "cn.damai:id/info_v2_price_layout",         # [U]
    "cn.damai:id/ll_concert_price",             # [L]
)
# 价格区间三段式 [L]：project_price_char='¥' + project_price_pre='288' + project_price_suffix='988'
PRICE_RANGE_IDS = (
    "cn.damai:id/project_price_char",
    "cn.damai:id/project_price_pre",
    "cn.damai:id/project_price_suffix",
)

# 预选入口（"设置本次抢票信息"横幅）——预约阶段详情页实测存在 [L]。
# 对应生态调研"预选机制"：App 自己记住场次/票档/张数/观演人，热路径压缩为 3 步。
PRESET_BANNER_IDS = (
    "cn.damai:id/goto_setinfo_tv2",        # text="设置本次抢票信息，抢票快人一步！"
    "cn.damai:id/goto_setinfo_btn_text",   # text="去设置"
)
PRESET_BANNER_TEXTS = ("设置本次抢票信息", "去设置")

# --- 购票 CTA（底部状态栏） ----------------------------------------------------

# 容器跨版本稳定：8.x[N] = 9.x[W] = 本机 9.0.38.6[L] 同名。
CTA_CONTAINER_ID = "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"

# 注意 [L]：预约阶段该容器存在但为空（无子节点、无可点击购票节点）——
# "容器存在"≠"按钮就绪"，改版探针必须区分容器级与按钮级就绪。
CTA_BUTTON_IDS = (
    "cn.damai:id/btn_buy_view",   # [U][W] sku 页确定按钮；详情页按钮历史上同 ID
)

# CTA 文案词表：文本或 content-desc 命中即视为按钮级就绪（图片化 CTA 可能只有 desc）。
CTA_READY_PATTERN = r"立即购买|立即预订|立即抢购|选座购买|立即购票"
CTA_RESERVE_PATTERN = r"立即预约|预约抢票|提交抢票预约|预约想看"
CTA_BLOCKED_PATTERN = r"已售罄|全部售罄|缺货登记|即将开抢|开售提醒|暂未开售|已结束"

# 预约状态标记 [U] page_probe._RESERVATION_TEXT_MARKERS
RESERVATION_TEXT_MARKERS = ("预约想看场次", "预约想看票档", "提交抢票预约", "已预约")

# --- SKU / 票档页 --------------------------------------------------------------

SESSION_PICKER_IDS = ("cn.damai:id/sku_panel_dates",)          # [U]
SESSION_PICKER_TEXTS = ("请选择场次", "选择日期", "请选择日期", "请选择演出日期")  # [U]

# 票价容器 + 索引选择：票价 Text 可能为空串（图片化）[W 实证][U 同结论]。
PRICE_PANEL_CONTAINER_IDS = (
    "cn.damai:id/project_detail_perform_price_flowlayout",  # [U][W]
    "cn.damai:id/layout_price",                              # [U]
)
PRICE_SOLD_OUT_TEXTS = ("已售罄", "全部售罄", "无票", "暂无可售票档", "缺货登记")  # [U]

QUANTITY_CONTAINER_ID = "cn.damai:id/layout_num"   # [W]
QUANTITY_PLUS_ID = "cn.damai:id/img_jia"           # [W]

CONFIRM_BUTTON_IDS = ("cn.damai:id/btn_buy_view",)  # [U][W]
CONFIRM_BUTTON_TEXTS = ("确定",)                     # [W 备选]

# --- 订单确认页 -----------------------------------------------------------------

SUBMIT_TEXTS = ("立即提交", "提交订单")   # [W][U 备选文本]

# --- 登录/异常 ------------------------------------------------------------------

LOGIN_PROMPT_MARKERS = ("请先登录", "登录/注册")  # [U]

# --- 页面根特征（状态机粗判） ----------------------------------------------------

ACTIVITY_STATE_MAP = (("ProjectDetail", "detail_page"),)  # [U]（其余条目见上游实现）
