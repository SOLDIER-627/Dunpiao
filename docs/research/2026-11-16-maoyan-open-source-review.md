# 猫眼抢票开源实现核查

> 历史调研。2026-11-17 用户停止本地模拟器路线；开源实现比较仅供未来猫眼真机适配参考。当前任务见 [HaTickets 真机方案](../architecture/2026-11-17-hatickets-real-phone-plan.md)。

日期：2026-11-16。用户报告猫眼 App **现在能够登录**；尚未确认该登录发生在新建的本地 AVD 上。本文件区分仓库代码、作者声明与本项目实测。

## 参考仓库与可用结论

| 仓库 | 已核对源码 | 对本项目的价值 | 局限 |
|---|---|---|---|
| [Pactum7/ticket-grabbing](https://github.com/Pactum7/ticket-grabbing) | [MaoYanGoNew.js](https://github.com/Pactum7/ticket-grabbing/blob/main/MaoYan/MaoYanGoNew.js)、[MaoYanMonitor.js](https://github.com/Pactum7/ticket-grabbing/blob/main/MaoYan/MaoYanMonitor.js) | AutoX.js 无障碍操作；开售前预约态检查、购票按钮识别；余票监控按场次/最高价/观演人筛选 | `GoNew` 含固定坐标和无界循环；部分路径连续点击支付按钮，不能原样运行；当前界面兼容性未验证 |
| [TsungShr/ticket-sniper](https://github.com/TsungShr/ticket-sniper) | [maoyan_grab.js](https://github.com/TsungShr/ticket-sniper/blob/main/autoxjs/maoyan_grab.js)、[platforms/maoyan.py](https://github.com/TsungShr/ticket-sniper/blob/main/platforms/maoyan.py) | 本机时间等待、有限重试、ADB 与设备端脚本协调的结构参考 | 代码中使用短间隔循环和宽泛的文本匹配；有自动提交动作；不能把它的成功判定直接当作付款成功 |
| [xinyi-eng/damai-mcp](https://github.com/xinyi-eng/damai-mcp) | README 明确列出猫眼为待实现的业务封装 | ADB/页面探针分层思路可参考 | **不能列为已完成猫眼抢票的实现** |
| [Appium UiAutomator2 Driver](https://github.com/appium/appium-uiautomator2-driver) | 官方驱动说明支持 Android 模拟器和真实设备 | PC 端可重复的页面定位、状态采样与动作封装 | 本项目需在实际猫眼版本上验证可访问性树和弹窗状态 |

Pactum7 README 将猫眼分成“卡点抢票”和“余票监控”；后者说明选择观演人、刷新和通知。代码显示监控通过页面文本查找票价、筛选缺货项，按观演人数量调节张数。它也记录了有些设备上票档区域不及时进入无障碍树，需要人工刷新页面节点。上述是**实现机制**，不是本机的成功率证据。

## 路线判断

首版采用 **Mac Python 协调器 + Appium/UiAutomator2 + 单台 Android 15 ARM64 Google Play AVD**。先人工完成猫眼登录与演出页面采样，再按页面状态实现有限动作。Pactum7 的状态与场次/票价筛选规则是主要业务参考；TsungShr 的调度分层是次要参考。暂不直接安装、运行第三方抢票脚本，以免其固定坐标、自动提交和连续点击触发不可预期动作。

对两个开源仓库的公开速度或成功率描述不作承诺。模拟器中能登录仅通过第一关，查看票档、进入确认页、提交订单仍须分别实测。平台可能按设备环境和操作行为另行判断；本方案不改设备指纹，不逆向接口签名，也不自动处理验证码或支付。

## 下一轮需要采样的页面

1. 已登录首页、目标演出详情、开售前预约态和开售按钮。
2. 场次列表、票档列表、缺货/无票、选座与非选座两条分支。
3. 张数、观演人选择、订单确认、支付页；订单状态只在用户人工操作时采样。
4. 网络错误、排队、验证码、登录失效、访问拒绝、未知弹窗。

样本只放被 Git 忽略的 `pagesamples/maoyan/`，截屏分享前遮盖姓名、手机号、证件与订单信息。
