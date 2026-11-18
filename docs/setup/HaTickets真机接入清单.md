# 实体安卓手机 USB 首轮接入

更新：2026-11-17。按[当前真机方案](../architecture/HaTickets真机接入方案_2026-11-17.md)执行。首轮只验证连接和大麦现有登录态。

1. 在实体安卓手机上人工打开大麦 App，确认仍已登录、能浏览一场非热门演出。不要退出账号、清除 App 数据或重装。
2. 用能传数据的 USB 线连接 Mac；手机开启开发者选项和 USB 调试，在手机出现授权提示时由用户本人确认。
3. Mac 上使用 Ticket 目录保留的官方工具：`/Users/Admin/Desktop/work/Ticket/.android-sdk/platform-tools/adb devices -l`。预期只有一台实体手机且状态为 `device`；不要把设备序列号发到聊天里。后续运行 HaTickets 时，在**当前终端**把 `/Users/Admin/Desktop/work/Ticket/.android-sdk/platform-tools` 加入 `PATH`，无需重新安装 Android 模拟器。
4. 只读核对 Android 版本与手机型号。若为 Android 12–14，符合 HaTickets README 推荐范围；其他版本先记为待测。
5. 在保持 USB 连接的情况下由用户人工再次操作大麦 App，确认登录态与普通浏览正常。此轮不安装 u2、不启动投屏或购票脚本。

记录：时间、脱敏型号、Android 版本、大麦 App 版本、ADB 状态、人工浏览结果、异常提示。截图/日志只在本地 `pagesamples/` 或 `logs/` 保存并在分享前脱敏。完成 PH-01 后再准备 Python 与 HaTickets `--probe` 环境。
