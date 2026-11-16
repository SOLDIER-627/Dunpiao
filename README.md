# dunpiao 蹲票

目标：开发一个在**用户自己的账号**上辅助购买演出票的本地脚本。第一版适配大麦 Android App，随后适配猫眼。当前阶段为仓库与任务整理；脚本尚未实现，也未在真实售票中验证。

> **为什么叫 dunpiao（蹲票）**：核心逻辑就是"开售前蹲守——定时等待、按设定时刻启动、有限重试"，取自抢票圈的说法。仓库可用 `dunpiao` 或 `dunpiao-ticket` 命名。

## 合规边界

脚本使用正常 App 界面操作。项目**不包含**验证码代解、接口签名逆向、账号批量注册、代理池或规避平台风控的功能。仓库不保存账号密码、短信验证码或证件号码；配置中的观演人信息只留在本地。

## 项目范围

- 提前配置演出、场次、票档、张数和已在 App 中维护的观演人。
- 开售前检查登录状态和目标页面，按设定时刻启动。
- 在 App 中完成选择、尝试下单、失败重试与结果通知；支付由用户确认。
- 显示每一步状态和失败原因，支持随时停止、限制尝试次数。
- 大麦先行；猫眼复用调度、日志和配置模块，单独实现页面适配。

## 仓库结构

当前实际布局：

```text
dunpiao/
├── README.md                 项目入口与当前状态
├── TASKS.md                  开发任务与验收条件
├── LICENSE                   MIT 许可证
├── scripts/doctor.py         安卓环境自检（只读）
└── docs/
    ├── architecture/         实现方案
    ├── setup/                环境安装与验证记录
    ├── research/             公开资料调研
    └── archive/              已被当前目标取代的旧方案
```

目标布局（随 DM-03 落地，逐步补齐）：

```text
dunpiao/
├── src/dunpiao/
│   ├── coordinator.py        运行协调器：定时、停止、重试、超时
│   ├── config.py             配置加载与校验
│   ├── logging_setup.py      日志与个人信息脱敏
│   ├── notify.py             结果通知
│   └── platforms/
│       ├── base.py           平台适配器接口（页面状态机）
│       ├── damai.py          大麦页面适配
│       └── maoyan.py         猫眼页面适配（P2）
├── config.example.yaml       配置模板（不含真实个人信息）
├── config.local.yaml         本地配置（gitignore，不入仓库）
├── tests/                    单元测试与页面状态识别测试
└── scripts/doctor.py         安卓环境自检（只读）
```

约束：`config.local.*`、`.env`、`logs/`、`screenshots/`、`.android-sdk/`、`.android-avd/` 均已在 `.gitignore` 排除，任何账号与证件信息不得进入 git 历史。

## 已确认的选择

- 平台顺序：**先大麦，再猫眼**。
- 调试设备：模拟器优先（开发进行中）；若票务 App 限制模拟器登录，按 DM-02 验证结果转真机。
- 语言：Python；界面控制选 Appium/UiAutomator2，先做可观察、可暂停的单账号流程。

## 环境自检

运行 `python3 scripts/doctor.py --json`，查看 Python、Java、Android SDK、`adb`、模拟器和已连接设备。脚本会优先检测仓库内 `.android-sdk/`，再回退到系统 PATH 和 `~/Library/Android/sdk`。返回码 1 表示缺少 `adb` 或模拟器工具；不会修改本机环境。环境安装记录见 [docs/setup/environment.md](docs/setup/environment.md)。

## 下一步

按 [TASKS.md](TASKS.md) 的 P0 顺序准备安卓环境、验证大麦 App 在模拟器上的登录与页面可访问性，然后实现最小下单流程。详细方案见 [docs/architecture/implementation-plan.md](docs/architecture/implementation-plan.md)。

## 资料

公开资料和仓库样本见 [docs/research/抢票代抢生态与开源实现调研_2026-11-16.md](docs/research/抢票代抢生态与开源实现调研_2026-11-16.md)。资料中的卖家承诺与 GitHub README 属各自陈述，不代表脚本实测成功率。
