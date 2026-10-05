# V1 本地 Runtime 使用

Runtime 使用 Python、Pydantic 和 PyYAML，提供状态提交校验和本地事务记录。它不负责规划业务内容、调度 Agent 或认证用户身份。

## 安装与自检

在仓库根目录使用 Python 3.13 参考环境：

```powershell
python -m venv .venv-imperialflow
& .\.venv-imperialflow\Scripts\python.exe -m pip install -r requirements-governance-lock.txt
& .\.venv-imperialflow\Scripts\python.exe -m unittest discover -s tests/governance -p 'test_*.py' -v
& .\.venv-imperialflow\Scripts\python.exe -m imperialflow --help
& .\.venv-imperialflow\Scripts\python.exe -m imperialflow schema
```

测试使用临时合成任务，不读取、写入或启动读者的实际项目任务。不要把 fixture 中的用户决定或角色身份移植成真实授权。

本仓库没有预置真实 Registry。`schema` 可独立执行；`status / begin / check / submit / render` 需要项目自身有效的 V1 Registry。迁移需可信维护者核对既有状态并冻结源文件，由 `Runtime.bootstrap(metadata, evidence, expected_sha256)` 一次导入。导入要求所有 task 的 metadata、真实证据及冻结的 Registry 哈希；不是自然语言审批的替代品，也不是日常状态编辑入口。

原项目的历史迁移脚本具有专用任务绑定，未随本仓库发布。V1 尚无通用新项目初始化或自动建任务命令。

## 正式提交顺序

`context.json` 表达可信入口提供的 Invocation：

```json
{
  "id": "<unique-invocation-id>",
  "actor": {"role": "ZHONGSHU", "identity": "<trusted-actual-identity>"}
}
```

这是结构示例，不是可用身份凭证。角色与实际身份由可信入口核对，Agent 不能自行冒充皇帝或审查者。

在已经初始化的项目里，依次执行：

```powershell
& .\.venv-imperialflow\Scripts\python.exe -m imperialflow begin --task <Task-ID> --context <context.json>
& .\.venv-imperialflow\Scripts\python.exe -m imperialflow check --context <context.json> --request <request.json>
& .\.venv-imperialflow\Scripts\python.exe -m imperialflow submit --context <context.json> --request <request.json>
```

其他工作目录可在子命令前使用 `--root <Project-Root>`。`begin` 登记调用并写技术事件，`action=null`；它不是额外的最终 Action。准备 request 时必须使用 begin 后的最新 Registry revision。

`check` 不写状态。`submit` 再次验证，成功后 Invocation finalized，只能登记一个最终 Action。拒绝请求不能被登记成完成。

## Typed Action 与证据

[TransitionRequest Schema](../imperialflow/schemas/transition_request.schema.json) 定义协议：`request_id`、`invocation_id`、`task_id`、`expected_revision`、`actor`、`result`、`routing`、`action`、`target_state`、`evidence_refs` 和 `artifacts`。额外字段拒绝，布尔声明不能代替证据。

EvidenceArtifact 绑定任务、类型、作者、路径、SHA256、VALID / VOID 状态；需要时绑定 plan_ref、package_ref、validation_ref，以及精确 start / end 区段。证据文件必须位于项目根目录内。LF / PACKAGE 归一化由 [evidence.py](../imperialflow/runtime/evidence.py) 定义，手工随意改换哈希规则会造成拒绝。

角色只能提出自己实际完成的 Action。状态边、结果类型、下一角色、目标阶段和证据链必须一致。Runtime 检查审查者与方案作者、验证者与交付作者身份不同；真实身份的真实性仍由可信入口负责。

## 事务、Trace 与恢复

提交路径为 Typed Action → Validator → Registry → Append Trace / Evidence → Derived View。Runtime 使用排他文件锁、expected_revision 与原始 Registry 哈希避免陈旧或并发写入。Registry 文件通过原子替换更新；多文件事务用待完成日志恢复。

Trace 保存序号、时间（UTC+08:00）、Task、Actor、原与目标状态、Result、Action、路由、证据、前事件哈希和 Registry 哈希。加载校验链与当前 Registry / 视图；提交同时校验绑定证据。

```powershell
& .\.venv-imperialflow\Scripts\python.exe -m imperialflow render
& .\.venv-imperialflow\Scripts\python.exe -m imperialflow recover
```

`render` 从经核对的 Registry 派生视图。`recover` 只处理存在的待完成事务；现有 Registry / Trace / Evidence 必须匹配事务前或事务后内容，外部变更会拒绝恢复。强制终止留下的锁由可信操作员核对持有进程后处理，不能盲删锁或直接改状态。

## 维护与错误

PERSONNEL 的维护调用使用 `begin --maintenance`，状态协调使用 `begin --reconciliation`；它们分别限制为合法治理 Action，不授予科研执行权。

常见拒绝代码：`ROLE_CAPABILITY_VIOLATION`、`ROLE_MISMATCH`、`INVALID_STATE_TRANSITION`、`TASK_START_AUTHORIZATION_MISSING`、`IMPERIAL_AUTHORIZATION_MISSING`、`IMPERIAL_ACCEPTANCE_MISSING`、`EVIDENCE_MISSING`、`VOID_ARTIFACT_REFERENCE`、`STATE_CONFLICT`、`INVOCATION_ALREADY_FINALIZED`、`BUDGET_EXCEEDED`。

CLI 拒绝输出 `validator_result: DENY` 与原因，退出码 2。失败不写正式状态迁移、完成 Evidence 或派生视图；新证据草稿和已单独完成的 begin 技术事件不因此回滚。完整约束见[已知边界](limitations.md)。
