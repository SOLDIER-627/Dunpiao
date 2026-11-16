# 分工计划

更新：2026-11-16。两个助手并行工作：**GPT** 负责 computer use 与安卓虚拟机操作，**Claude（pi）** 负责编码与仓库归档。本文约定各自负责的任务、产出物和交接方式。

## 角色划分

### GPT —— 环境与真机/模拟器操作
擅长的部分：computer use（图形界面操作）、安卓虚拟机安装调试。

| 任务 | 内容 | 产出物 |
|---|---|---|
| DM-01 | 安装 Android SDK、模拟器、adb，创建并启动 AVD | 可用模拟器；更新 `docs/setup/environment.md`（SDK 路径、AVD 名称、系统版本、`adb devices` 结果） |
| DM-02 | 在模拟器上安装大麦 App，用户手动登录后，探索演出详情页→票档→确认→支付各页面 | 页面样本（见下方"页面样本约定"）；环境与 App 版本记录 |
| DM-04 协助 | 验证脚本对页面状态的识别是否正确，在模拟器上实际运行并反馈 | 运行结果、失败截图、uiautomator dump |
| DM-07 协助 | 端到端验证时实际操作模拟器 | 完整流程日志 |

### Claude（pi）—— 编码与仓库
擅长的部分：Python 编码、模块设计、git/文档归档。

| 任务 | 内容 |
|---|---|
| DM-03 | 搭建 `src/dunpiao/` 项目骨架：配置加载校验、日志与脱敏、启动/停止命令 |
| DM-04 | Appium/UiAutomator2 接入代码、页面状态识别（依据 GPT 提供的页面样本） |
| DM-05/06 | 开售等待、票档/观演人选择、有限重试、可中止逻辑 |
| 全程 | `scripts/doctor.py` 维护、单元测试、错误处理 |
| 归档 | 维护 `Dunpiao/` GitHub 仓库（已推送 https://github.com/SOLDIER-627/Dunpiao ），按路径选择性归档代码与 README |

## 页面样本约定（GPT → Claude 的交接格式）

GPT 在探索大麦 App 页面时，把每个状态的材料放入 `pagesamples/`（不入 git，已加 .gitignore）：

```text
pagesamples/
├── 01-not-logged-in/
│   ├── dump.xml          adb shell uiautomator dump 的输出
│   └── screenshot.png
├── 02-performance-detail/
├── 03-ticket-tier/
├── 04-confirm/
├── 05-pay/
├── 06-sold-out/
└── 07-popup-*/           各种弹窗（更新提示、广告、权限等）
```

每个目录可附 `notes.md`，写清楚：从上一状态如何进入本状态、关键控件文本、点击后的跳转。Claude 依据 dump.xml 编写定位器，GPT 在模拟器上验证。

## 工作流

1. **GPT 先行**：完成 DM-01/02 的环境与页面探索，产出页面样本。
2. **Claude 编码**：基于样本实现 DM-03/04，跑通"识别页面状态"。
3. **闭环迭代**：GPT 在模拟器上运行脚本验证 → 反馈 dump/截图 → Claude 修定位器与流程。
4. **归档**：代码与 README 稳定后，Claude 同步到 `Dunpiao/` 并 push GitHub。

## 边界与注意事项

- **不要动对方的目录**：GPT 不要改 `src/dunpiao/` 与 `Dunpiao/`；Claude 不动 `.android-sdk/`、`.android-avd/`、`pagesamples/` 和模拟器。
- **两个 git 仓库**：`Ticket/`（工作区，全量）与 `Ticket/Dunpiao/`（GitHub 归档，精简）。双方在 `Ticket/` 提交；归档由 Claude 操作，方向永远是 工作区 → Dunpiao → GitHub。
- **敏感信息**：账号、验证码、证件号不进任何 git 仓库；登录由用户手动完成，脚本不碰凭据。
- **安全第一**：脚本能随时停止、最多一次有效订单、不自动支付。任何不确定的页面状态一律安全停止。
