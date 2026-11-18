# HaTickets 真机路线核查

核查日期：2026-11-17。参考仓库：[currycan/HaTickets](https://github.com/currycan/HaTickets)。本文件只记录公开仓库的当前说明和本项目尚未完成的验证，不把上游声明当成我们账号的成功结果。

## 上游实际路线

| 主题 | 上游依据 | 对本项目的决定 |
|---|---|---|
| 运行载体 | [README](https://github.com/currycan/HaTickets#适用人群与准入门槛)明确 Mobile 需要 Android 12–14 真机、已登录大麦、ADB 可见；模拟器易被风控 | 用用户近期已成功登录大麦的实体 Android 手机；先核对手机系统版本，15+ 作为兼容性待测 |
| 驱动 | [README 方案状态](https://github.com/currycan/HaTickets#方案状态)标注 Mobile 使用 Python `uiautomator2` 直连，无 Appium 中间服务；[pyproject](https://github.com/currycan/HaTickets/blob/master/pyproject.toml)依赖 `uiautomator2`、`adbutils` | 首轮只用 adb 与 u2，避免同时安装 Appium 和 AutoX；scrcpy 仅用于人工投屏，可后装 |
| 启动门槛 | [quick-start](https://github.com/currycan/HaTickets/blob/master/docs/quick-start.md)先 `adb devices`、检查 App 登录及观演人，再准备本地配置 | 设备必须只有一台且为 `device`；不清除 App 数据、不强制重新登录 |
| 安全探测 | [README](https://github.com/currycan/HaTickets#三个旗标的语义)定义 `--probe` 在购票入口前停止，不提交 | 第一轮运行只做探测，验收前台页面与目标演出识别；不以此声称下单可用 |
| 提交闸门 | 同一 README 定义 `--commit` 才能给单次进程授予提交权限，`--yes` 单独不能提交 | 本项目保留探测与提交权限隔离，提交需独立验收与用户监督 |
| 配置 | [配置模板](https://github.com/currycan/HaTickets/blob/master/mobile/config.example.jsonc)包含 serial、目标演出、城市、日期、票档、观演人、探测与提交标志 | 只用本地忽略 Git 的配置文件；真实姓名和设备序列号不进仓库或聊天 |
| Python | 上游 [README 推荐环境](https://github.com/currycan/HaTickets#推荐环境)为 Python 3.10–3.13、Poetry 1.7+；仓库 `pyproject.toml` 约束 `<3.14` | 当前 Mac 自带 Python 3.9.6，不直接当成上游推荐环境；在运行前准备项目隔离的 3.12/3.13 环境 |

上游的 `mobile/damai_app/` 拆分了页面探测、抢票流程、等待和恢复等模块；其 [流程文档](https://github.com/currycan/HaTickets/blob/master/docs/mobile-ticket-logic.md)显示 `u2.connect(serial)`、保持 App 会话、识别详情页/票档/确认页等机制。文档中仍有旧 Appium/WebDriver 描述，实施时以当前 Mobile 代码和 README 为准，不能把混用的旧段落直接照搬。

## 本项目与上游的距离

我们已完成的只有：同账号近期在实体 Android 手机的大麦 App 成功登录（用户报告），并保留了官方 ADB Platform-Tools。**尚未连接真机**、未检查 Android 版本与 USB 授权、未安装 u2/Poetry、未运行 HaTickets `--probe`，也没有真机自动下单结果。

先在隔离的参考目录取得并固定 HaTickets 版本，检查许可证与启动脚本，再做只读 `--probe`。如果该设备的系统版本超出上游推荐范围，记录原始兼容性结果，不直接改系统或切换账号。我们自己的项目首版采用其直连与双模式门槛，不需要复制上游全部热路径优化。
