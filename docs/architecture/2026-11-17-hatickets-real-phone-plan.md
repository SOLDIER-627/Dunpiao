# 以 HaTickets 为主线的多仓真机方案

更新：2026-11-17。项目主线是**大麦 App + 用户自己的实体 Android 手机 + Mac USB + Python uiautomator2 直连**。以 HaTickets Mobile 为主代码基线，结合其他仓库并按真机样本改造，见[多仓融合清单](../research/2026-11-17-multi-repo-integration.md)。猫眼模拟器、大麦模拟器和雷电云尝试均归档；猫眼后续复用真机连接层。来源核查见[HaTickets 真机路线](../research/2026-11-17-hatickets-real-phone-review.md)。

## 原则和边界

手机保持原厂系统、现有大麦 App 与已登录账号，不改机型、不 root、不导出会话。Mac 的 ADB 通过 USB 连接，u2 在通过基础连接检查后才启用。真实手机的身份是真实的，但平台仍可能识别自动化环境或操作；因此把“设备在线”“只读探测”“页面操作”“订单提交”分开验收。支付始终由用户本人完成。

不把 HaTickets 仓库直接视为已在本机可用：它的 README 推荐 Android 12–14、Python 3.10–3.13；上游已有 [Android 16 真机控件定位问题](https://github.com/currycan/HaTickets/issues/41)和[搜索/票档问题](https://github.com/currycan/HaTickets/issues/61)，需结合大麦 App 版本区分原因。2026-11-18 已确认 Xiaomi 14 / Android 16 / 大麦 9.0.38.6 的 USB 授权与人工浏览正常；Python 3.12 隔离环境已建，HaTickets 源码下载与 u2 只读探测未完成。接续见上级 Ticket 工作区的[Pi 编码交接](../../../docs/architecture/Pi编码交接_2026-11-18.md)。

## 分阶段执行

| 阶段 | 动作 | 验收 |
|---|---|---|
| PH-00 已有基线 | 用户近期在该真机的大麦 App 登录成功 | 再次由用户人工打开非热门演出确认会话仍有效 |
| PH-01 USB | 数据线接 Mac，开启开发者选项/USB 调试，在手机上授权这台 Mac；使用已保留的官方 `adb` | 仅一台实体设备显示 `device`，记录脱敏型号与 Android 版本；App 手动使用正常 |
| PH-02 环境与基线 | 在 Ticket 目录建立隔离环境，固定 HaTickets commit、依赖与许可证 | 上游原版与本项目改动可区分；配置无真实账号资料 |
| PH-03 只读探测 | 用户手动打开目标详情页；对照 HaTickets 原版和本项目改版 `--probe` | 差异有记录；识别正确，停在购票入口前 |
| PH-04 提交前流程 | 按真机页面样本，融合 WECENG/Lzhimie 的定位与流程并改造 HaTickets | 场次、票档、数量、观演人和金额吻合；未知页、断线、登录失效立即停 |
| PH-05 单次订单验收 | 用户决定后才运行单次提交模式，监督目标场次和金额 | 最多创建一张目标订单；检测到待支付立即停，由用户本人付款 |

PH-01 首轮只用 ADB，不同时启动 u2、scrcpy 或其他辅助服务。这样能区分 USB 接入本身与后续自动化组件的影响。PH-03 才按上游 `--probe` 的语义运行；它只能证明页面探测可用，不能证明下单成功。[Android 官方 ADB 文档](https://developer.android.com/tools/adb)说明手机端需授权 USB 调试；[HaTickets quick-start](https://github.com/currycan/HaTickets/blob/master/docs/quick-start.md)列出手机、配置和探测的顺序。

## 软件结构与采用范围

```text
本地配置（忽略 Git） → 运行入口：probe / commit
                       ↓
              目标与设备预检、单实例锁
                       ↓
              大麦页面状态机与订单核对
                       ↓
              uiautomator2 → USB ADB → 实体安卓手机
```

采用 HaTickets 的 **u2 直连、设备序列号明确选择、只读 probe、单次 commit 权限、状态判别与可停止运行**作为骨架；WECENG/Lzhimie 用于大麦定位与流程对照，Pactum7 用于后续猫眼适配，Guyungy 用于后期控制台。按真机样本修改代码，每项改动记录上游对照、结果和回退方式。性能参数在正确性验收后实测调整。根目录 `config.example.yaml` 是本项目的设计模板；运行上游 HaTickets 时必须使用它自己的 `mobile/config.example.jsonc` 复制出本地 `config.jsonc`，不能将 YAML 直接交给上游。上级 Ticket 工作区的 `scripts/diagnose_android_login.py` 可作只读环境摘要，真实截图放在被 Git 忽略的页面样本目录，分享前脱敏。原 USB 真机可行性分析见[历史方案](2026-11-16-usb-real-phone-plan.md)，以本文件的技术栈和阶段顺序为准。

## 失败分支

- `adb devices` 空：检查数据线、USB 模式、手机授权；不重装大麦。
- `unauthorized`：用户在手机上确认授权；不尝试复制或绕过授权。
- 真机手动大麦正常但 u2 探测后异常：记录前后时间和报错，停止该组件，不将问题归因于账号本身。
- Android 16 或其他不在上游推荐的 12–14 范围内：先做 ADB/u2 连接与只读 `--probe`，记录手机型号、大麦 App 版本及失败页面；区分系统兼容问题和新版控件变化，再决定适配。
- 页面内容不匹配或出现验证/拒绝：暂停并交给用户人工处理，不高频重试。

PH-01 已完成。下一实际动作由 Pi 补全 HaTickets 官方源码、固定版本并做只读 u2/`--probe` 兼容性检查。
