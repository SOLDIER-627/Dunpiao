# 多仓方案融合：HaTickets 为主

更新：2026-11-17。上级 Ticket 工作区的[完整模块清单](../../../docs/research/多仓方案融合与HaTickets改造清单_2026-11-17.md)是本项目当前实施依据。

主代码基线为 [HaTickets Mobile](https://github.com/currycan/HaTickets/tree/master/mobile)：固定上游 commit、依赖与许可证，先跑原版只读 `--probe`。之后以真实手机的脱敏页面样本为证据，修改其选择器、状态判断、异常处理和必要的性能参数。每项改动记录上游与改版结果及回退方式。

次要参考：[WECENG](https://github.com/WECENG/ticket-purchase/tree/master/damai_appium) 的大麦新版页面与票价索引；[Lzhimie](https://github.com/Lzhimie/damai-ticket-helper) 的场次和票档兜底；[Pactum7](https://github.com/Pactum7/ticket-grabbing/tree/main/MaoYan) 的猫眼流程；[Guyungy](https://github.com/Guyungy/damaihelper) 的后期控制台。跨仓代码移植前核对许可证，所有定位都在当前手机和 App 版本上重新验证。

执行顺序：USB 真机连接 → 固定上游基线 → 原版/改版只读探测 → 大麦提交前流程 → 用户监督单次提交 → 猫眼真机适配 → 可视化控制。当前尚未连接真机，流程能力未实测。
