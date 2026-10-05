# 角色职责与权限

ImperialFlow 的角色按工作职责划分。可信入口明确指定本次角色、身份与 Task ID，角色在提交成功后停止；路由不会自动启动另一角色。

## 三省与入口角色

| 角色 | 交付内容 | 停止位置 |
| --- | --- | --- |
| EMPEROR / 用户 | 真实启动、执行授权、暂停、取消、返工与验收决定 | 只登记该项实际决定 |
| PRINCE / 太子 | Intake、风险与任务分类、依赖、角色路由 | 路由下一角色后停止 |
| ZHONGSHU / 中书省 | 方案、版本、输入输出、假设、方法、单位、验收与风险 | 请求独立门下审查后停止 |
| MENXIA / 门下省 | 当前方案版本的独立 APPROVE / REJECT 与问题 | 交尚书准备执行或退回方案 |
| SHANGSHU / 尚书省 | 经批准方案的执行包、文件范围、职责、交付、验证与停止条件 | 请求用户执行授权后停止 |

中书不批准自己的方案；门下不整理执行包；尚书不代作用户执行授权。Intake 完成不代表方案已完成，技术 APPROVE 不代表执行授权已给出。

## 六部职责

| 职责 | ID | 主要内容 | 典型边界 |
| --- | --- | --- | --- |
| 吏部 / AgentOps | PERSONNEL | 工作流、Skill、Prompt、治理维护与受限协调 | 维护不推进业务生命周期 |
| 户部 / Data | REVENUE | 数据、指标、实验输入输出 | 不虚构未运行结果 |
| 礼部 / Documentation | RITES | README、报告、公式、交付说明 | 不在文档中改写批准方法 |
| 兵部 / Engineering | WAR | 代码、算法与工程实现 | 只实现批准范围 |
| 刑部 / QA | JUSTICE | 独立验证与验收标准检查 | 验证通过只请求用户验收 |
| 工部 / Infrastructure | WORKS | 环境、依赖、基础设施与部署 | 技术能力不扩大授权范围 |

执行职责按执行包排序。同一执行者可在另一次明确调用中承担另一职责；需要独立性的审查和验证必须另行安排满足要求的身份。作者自检不能记为独立通过。

## 三类审查

| 角色 | 审查对象 | 结果含义 |
| --- | --- | --- |
| MENXIA | PLAN / PRE-EXECUTION | 方案合理、完整、可执行，或明确退回原因 |
| JUSTICE | DELIVERABLE / POST-EXECUTION | 实际成果是否符合批准方案和验收标准 |
| YUSHITAI | PROCESS / GOVERNANCE / SYSTEM | 流程是否越权、跳过门禁、丢失证据或无限返工 |

御史台按明确授权的 Checkpoint 合同审计，通常不重复全部业务测试。`ACCEPT_CHECKPOINT` 只接受该治理检查，不使业务任务自动 `DONE`，也不启动下一版本。

## 机器能力矩阵

完整 Action 白名单由 [role_capabilities.json](../imperialflow/schemas/role_capabilities.json) 表达，Runtime 以该配置校验。它与状态边、证据和门禁共同决定请求是否合法；在白名单中不代表在任意状态都能提交。

| 角色 | 常见正常 Action |
| --- | --- |
| EMPEROR | START_TASK、APPROVE_EXECUTION、ACCEPT_DELIVERY |
| PRINCE | FORWARD_TO_ZHONGSHU；LOW 可按合同 FORWARD_TO_EXECUTOR |
| ZHONGSHU | REQUEST_MENXIA_REVIEW |
| MENXIA | APPROVE_PLAN、RETURN_FOR_REVISION |
| SHANGSHU | REQUEST_IMPERIAL_AUTHORIZATION |
| 执行部门 | FORWARD_TO_NEXT_EXECUTOR、REQUEST_JUSTICE_VALIDATION（按各角色白名单） |
| JUSTICE | REQUEST_IMPERIAL_ACCEPTANCE、RETURN_FOR_CORRECTION |
| PERSONNEL 治理维护 | GOVERNANCE_PATCH_COMPLETE、STATE_RECONCILED |
| YUSHITAI | REQUEST_IMPERIAL_CHECKPOINT_DECISION |

V1 允许 JUSTICE 在 VALIDATION 发现根本方案问题时受限 `RETURN_TO_ZHONGSHU`：撤下当前后续批准，重新规划；这不产生用户批准。同名用户决定仍须来自实际用户。

## 调用前核对

确认任务存在、启动证据有效、角色与路由匹配、前一角色动作实际完成、当前状态与绑定证据一致、写入范围属于当前角色。任何失败都不能靠补造授权或预写下一角色决定来“修复”。共享环境中的文件可写能力不等于职责授权。
