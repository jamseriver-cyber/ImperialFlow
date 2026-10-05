---
name: imperialflow
description: 按三省六部职责分次完成方案、独立审查、受控执行和证据交付，使用本地 Runtime 提交治理状态。
---

# ImperialFlow

这是公开参考 Skill。接入项目先确定用户授权、真实入口、文件范围及项目合同；本模板不包含实际任务启动或审批。

首次应用时告知用户。读取 [工作流](../../../docs/workflow.md)、[角色](../../../docs/roles.md)、[Runtime](../../../docs/runtime.md) 和[边界](../../../docs/limitations.md)。安装到另一目录时必须同步这些相对路径。

开始正式角色工作前，读目标项目 Canonical Registry、派生 CURRENT_STATE 与对应 task evidence；核对实际 START_TASK、当前角色、合法下一动作、证据和写入范围。NEXT_TASK 与模糊“继续”不能授权新任务。

一次 Invocation 只执行一个明确角色的一个阶段，产生一个最终 Action 后停止。HIGH / CRITICAL 不能绕过当前有效方案的独立审查、执行包与适用的用户授权。发现方法根本问题，使用本角色报告 Action，不同轮改方案或替下一角色决策。

当前状态只经 Typed Action → Runtime Validator → Registry → Append Trace / Evidence → Derived View 提交；禁止手改 Registry / view，禁止覆写历史头部。check 不提交，submit 成功才登记 Action。

最后按 Result / Decision、Routing、Action 三段输出。Action 使用机器角色白名单，结果与 Action 分开；验证通过只请求用户验收，不能代写 ACCEPT_DELIVERY 或 DONE。

治理维护与受限状态协调使用 PERSONNEL 维护入口，不改变业务任务范围或提升阶段。临时范围需求按 Interrupt 分类；Checkpoint 独立于普通交付验收。

共享文件系统没有 OS 角色隔离，Actor 依赖可信本地入口；不要宣称已实现真实身份签名、工具隔离、自动新任务创建或自动跨阶段调度。
