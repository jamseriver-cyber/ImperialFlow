# 工作流规则

本文件总结当前 V1 规则。可执行状态边以 [state_machine.py](../imperialflow/runtime/state_machine.py)、请求校验以 [validator.py](../imperialflow/runtime/validator.py) 为准；规范目标与尚未通用实现的路线见[已知边界](limitations.md)。

## 启动与一次调用

路线图、候选任务、NEXT_TASK、NEXT_ROLE 和 NEXT_ACTION 均不产生启动权。新任务进入 Intake 前，须有实际用户绑定明确 Task ID 的启动决定。下列仅为格式示例，不是有效授权：

```text
ACTION: START_TASK
TASK_ID: EXAMPLE-T01
```

可信入口据真实来源登记该决定。`START_TASK` 只到 `AUTHORIZED`；另一次 PRINCE 的 `begin` 才进入 `INTAKE`。它不授予方案批准、执行授权或最终验收。

每次正式调用执行 ONE ROLE — ONE STAGE — ONE ACTION：读取当前状态，核对权限，完成自己的工作，提交一个 Typed Action，提交成功后停止。下一角色由可信入口另行调用。

## 生命周期

```text
NOT_STARTED → AUTHORIZED → INTAKE → PLAN → REVIEW
→ EXECUTION_PREP → AWAITING_IMPERIAL_AUTHORIZATION
→ EXECUTION → VALIDATION → AWAITING_IMPERIAL_ACCEPTANCE → DONE
```

异常位置包括 `BLOCKED`、`CHANGES_REQUESTED`、`CANCELLED`、`VOID`。`EXECUTION` 表示门禁已满足、可以进入执行调用，实际完成仍要查看交付证据和 `execution_status`。旧兼容字段与新 `runtime.state` 可能表达不同粒度，不能仅凭历史 phase 判断最新授权。

## 正常交接与证据

| 本轮实际 Action | 提交所需阶段证据 | 下一位置 |
| --- | --- | --- |
| START_TASK | 实际用户启动决定，绑定 Task ID | PRINCE / AUTHORIZED |
| FORWARD_TO_ZHONGSHU | Intake 完成 | ZHONGSHU / PLAN |
| REQUEST_MENXIA_REVIEW | 当前 PLAN 与版本 | MENXIA / REVIEW |
| APPROVE_PLAN | 独立审查，绑定当前 PLAN | SHANGSHU / EXECUTION_PREP |
| REQUEST_IMPERIAL_AUTHORIZATION | 执行包，绑定 PLAN，明确 scope 与职责 | EMPEROR / 授权等待 |
| APPROVE_EXECUTION | 实际用户决定，绑定当前 PLAN 和执行包 | 首个获派执行职责 / EXECUTION |
| FORWARD_TO_NEXT_EXECUTOR | 当前部门实际交付 | 执行包中的下一职责 |
| REQUEST_JUSTICE_VALIDATION | 执行范围内的完整交付 | JUSTICE / VALIDATION |
| REQUEST_IMPERIAL_ACCEPTANCE | 独立 VALIDATION_PASS，绑定当前 PLAN | EMPEROR / 验收等待 |
| ACCEPT_DELIVERY | 实际用户验收，绑定当前 PLAN 与实际验证记录 | DONE |

HIGH / CRITICAL 执行需要当前有效方案的独立审查、执行包与适用的用户授权。旧版批准不能覆盖新版方法。测试通过不等于独立验证通过；验证通过不等于用户验收。

## 正式输出

阶段正文说明实际完成内容、证据、风险和未完成项；最后以如下结构结束。这是格式模板，不是已发生的 Action：

```text
## Result / Decision
RESULT: <本角色的实际结果>

## Routing
NEXT_ROLE: <合法下一角色或 null>
NEXT_PHASE: <合法下一阶段或 null>

## Action
ACTION: <本角色白名单中的单一动作>
```

门下审查使用 `DECISION: APPROVE / REJECT`。自然语言格式用于人阅读；正式状态变更依赖 Runtime 接受的 Typed Action，`check` 的 ALLOW 不表示已经提交。

## 返工与作废

门下 REJECT 退回中书；刑部发现实现问题退回合法执行者，发现根本方案问题受限退回中书。执行者只报告问题，不同轮改方案并模拟审查。

默认 `max_revisions / max_review_rounds / max_execution_retries` 各为 2。对应 Action 达到计数上限时被拒绝；review_rounds 的具体累计按 Runtime Action 规则执行，不能误写为“两轮返工之外还有无限审查”。预算不重置，不自动增加，交用户处理范围或后续决定。

未经授权或已作废的记录保留为 `VOID / UNAUTHORIZED` 历史，不能作为当前方案、审查或执行依据。有效证据必须有精确区段与正确哈希，不能把 VOID 内容重新标为 VALID 复用。

## 临时需求

用户新增临时需求通过 `IMPERIAL_INTERRUPT` 保存阻塞前位置并交 PRINCE。旧执行调用被标记 interrupted，不能继续提交交付。

| 分类 | 当前任务的处理 |
| --- | --- |
| NOTE | 附加说明并恢复原路由，不改变 scope |
| NEW_TASK | 保持新需求独立；仍需明确新 Task ID 的 START_TASK |
| CHANGE_REQUEST / URGENT_FIX | 非治理范围变更退回中书，当前后续批准失效；治理影响交吏部 |
| HOLD / CANCEL | 太子分类后交用户决定；太子不能代作暂停或取消 |

用户也可直接实际 `HOLD / CANCEL`。紧急程度不豁免门禁，执行部门不能顺手扩大 scope。

## 状态协调与治理维护

PERSONNEL 的受限 `STATE_RECONCILED` 只恢复已保存的阻塞前位置，并提供真实治理证据；不能选择一个更高阶段或补造批准。派生视图过时可由 `render` 重建；Registry、Trace 或绑定证据缺失与外部改动不能凭一句“已修好”覆盖。

`GOVERNANCE_PATCH_COMPLETE` 记录治理维护结果，保持业务任务的 phase、status、last_action 与路由。维护和 Checkpoint 不自动启动新业务任务。
