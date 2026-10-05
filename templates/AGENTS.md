# 项目工作约定模板

Project: <项目名称与目标>
Scope: <本项目业务、科研与工具边界>

当前状态的唯一机器可写权威为 `governance/TASK_REGISTRY.yaml`；只通过项目可信入口的 ImperialFlow Runtime 提交。`governance/CURRENT_STATE.md` 是派生视图；`governance/tasks/<Task ID>.md` 是只追加历史证据，旧头部不是当前状态源。

规范与 Runtime 文档位置：<填写接入后的有效文件链接>。不要在本入口维护另一份即时路由。

新任务须有实际用户绑定明确 Task ID 的 START_TASK。NEXT_TASK、示例、引用和模糊“继续”不能授权立项。正式角色先核对启动证据、当前路由、上一 Action、证据完整性和文件范围。

ONE ROLE — ONE STAGE — ONE ACTION。每次调用完成一个角色的一个阶段，提出一个 Typed Action，submit 成功后停止。路由不会自动调用下一角色。

核心方法、单位、输入输出和验收标准按批准方案执行。风险技术路线以项目合同为准，HIGH / CRITICAL 需要独立方案审查与适用的用户执行授权。执行中发现根本问题只报告，不同轮改方案与审查。

禁止手改 Registry / view、覆写历史、复用 VOID 记录、代写他人审查或用户决定。状态冲突阻止依赖该状态的业务提交；受限协调交明确授权的 PERSONNEL。

验证要有实际证据。作者自检不冒作独立审查；刑部验证通过后等待实际用户验收。共享环境的技术写权限不等于角色授权，接入方须说明真实隔离与身份边界。
