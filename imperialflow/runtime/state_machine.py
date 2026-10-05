from dataclasses import dataclass

from .errors import GovernanceError, require
from .models import Action as A, Phase as P, Role as R, TaskState as S


EXECUTORS = {R.WAR, R.RITES, R.REVENUE, R.WORKS, R.PERSONNEL}
BLOCKER_ACTIONS = {
    A.REPORT_STATE_CONFLICT, A.REPORT_PLAN_BLOCKER, A.REPORT_EXECUTION_BLOCKER,
    A.REPORT_GOVERNANCE_CONFLICT, A.REPORT_PLAN_DEFECT, A.REPORT_CRITICAL_FINDING,
    A.HOLD_FOR_STATE_RECONCILIATION, A.REJECT_INVALID_REQUEST,
    A.REQUEST_ROUTE_CHANGE,
}


@dataclass(frozen=True)
class Route:
    state: S
    role: R | None
    phase: P | None


FIXED = {
    A.START_TASK: ({S.NOT_STARTED}, Route(S.AUTHORIZED, R.PRINCE, P.INTAKE)),
    A.FORWARD_TO_ZHONGSHU: ({S.INTAKE}, Route(S.PLAN, R.ZHONGSHU, P.PLAN)),
    A.REQUEST_MENXIA_REVIEW: ({S.PLAN, S.CHANGES_REQUESTED}, Route(S.REVIEW, R.MENXIA, P.REVIEW)),
    A.APPROVE_PLAN: ({S.REVIEW}, Route(S.EXECUTION_PREP, R.SHANGSHU, P.EXECUTION_PREP)),
    A.RETURN_FOR_REVISION: ({S.REVIEW}, Route(S.CHANGES_REQUESTED, R.ZHONGSHU, P.PLAN)),
    A.REQUEST_IMPERIAL_AUTHORIZATION: ({S.EXECUTION_PREP}, Route(S.AWAITING_IMPERIAL_AUTHORIZATION, R.EMPEROR, P.AWAITING_IMPERIAL_AUTHORIZATION)),
    A.REQUEST_JUSTICE_VALIDATION: ({S.EXECUTION}, Route(S.VALIDATION, R.JUSTICE, P.VALIDATE)),
    A.REQUEST_IMPERIAL_ACCEPTANCE: ({S.VALIDATION}, Route(S.AWAITING_IMPERIAL_ACCEPTANCE, R.EMPEROR, P.AWAITING_IMPERIAL_ACCEPTANCE)),
    A.ACCEPT_DELIVERY: ({S.AWAITING_IMPERIAL_ACCEPTANCE}, Route(S.DONE, None, None)),
}


def expected_route(task, request):
    state = S(task["runtime"]["state"])
    action = request.action.type
    if action == A.IMPERIAL_INTERRUPT:
        require(state != S.NOT_STARTED, "INVALID_STATE_TRANSITION", "No active task")
        return Route(S.BLOCKED, R.PRINCE, P.INTAKE)
    if action == A.CLASSIFY_INTERRUPT:
        require(state == S.BLOCKED and task["runtime"].get("interrupt_pending"),
                "INVALID_STATE_TRANSITION", "No unclassified interrupt")
        item = request.interrupt
        require(item is not None, "EVIDENCE_MISSING", "Interrupt classification")
        saved = task["runtime"].get("resume")
        require(bool(saved), "EVIDENCE_MISSING", "Interrupted state snapshot")
        if item.classification in {"NOTE", "NEW_TASK"}:
            require(item.impact == "none", "INVALID_STATE_TRANSITION", "No change to current task scope")
            return Route(S(saved["state"]), R(saved["role"]) if saved["role"] else None,
                         P(saved["phase"]) if saved["phase"] else None)
        if item.classification in {"HOLD", "CANCEL"}:
            return Route(S.BLOCKED, R.EMPEROR, None)
        if item.impact == "governance":
            return Route(S.BLOCKED, R.PERSONNEL, P.EXECUTE)
        return Route(S.CHANGES_REQUESTED, R.ZHONGSHU, P.PLAN)
    if action in FIXED:
        sources, route = FIXED[action]
        require(state in sources, "INVALID_STATE_TRANSITION", f"{state} cannot {action}")
        return route
    if action == A.APPROVE_EXECUTION:
        require(state == S.AWAITING_IMPERIAL_AUTHORIZATION, "INVALID_STATE_TRANSITION", str(state))
        roles = task["runtime"].get("execution_roles", [])
        require(bool(roles), "EVIDENCE_MISSING", "Approved execution department sequence")
        return Route(S.EXECUTION, R(roles[0]), P.EXECUTE)
    if action == A.FORWARD_TO_NEXT_EXECUTOR:
        require(state == S.EXECUTION, "INVALID_STATE_TRANSITION", str(state))
        roles = task["runtime"].get("execution_roles", [])
        require(request.actor.role.value in roles, "ROLE_MISMATCH", "Executor not assigned")
        idx = roles.index(request.actor.role.value) + 1
        require(idx < len(roles), "INVALID_STATE_TRANSITION", "Last executor must request validation")
        return Route(S.EXECUTION, R(roles[idx]), P.EXECUTE)
    if action == A.FORWARD_TO_EXECUTOR:
        require(state == S.INTAKE and task["risk"] == "LOW", "INVALID_STATE_TRANSITION", "Only approved LOW shortcut")
        roles = task["runtime"].get("execution_roles", [])
        require(bool(roles), "EVIDENCE_MISSING", "Task-start scope must assign executor")
        return Route(S.EXECUTION, R(roles[0]), P.EXECUTE)
    if action == A.RETURN_FOR_CORRECTION:
        require(state == S.VALIDATION, "INVALID_STATE_TRANSITION", str(state))
        role = request.routing.next_role
        require(role in {R.WAR, R.RITES, R.REVENUE, R.WORKS}, "INVALID_STATE_TRANSITION", "Correction executor required")
        require(role.value in task["runtime"].get("execution_roles", []), "ROLE_MISMATCH", "Unassigned correction executor")
        return Route(S.EXECUTION, role, P.EXECUTE)
    if action in {A.RETURN_TO_ZHONGSHU, A.REQUEST_CHANGES}:
        require(state not in {S.NOT_STARTED, S.AUTHORIZED, S.INTAKE}, "INVALID_STATE_TRANSITION", str(state))
        if request.actor.role == R.JUSTICE:
            require(state == S.VALIDATION, "INVALID_STATE_TRANSITION", "JUSTICE scope: post-execution plan defect")
        return Route(S.CHANGES_REQUESTED, R.ZHONGSHU, P.PLAN)
    if action in BLOCKER_ACTIONS or action == A.HOLD:
        require(state != S.NOT_STARTED, "INVALID_STATE_TRANSITION", "No started task to block")
        return Route(S.BLOCKED, R.PRINCE if action == A.REQUEST_ROUTE_CHANGE else request.actor.role,
                     P.INTAKE if action == A.REQUEST_ROUTE_CHANGE else request.routing.next_phase)
    if action == A.CANCEL:
        return Route(S.CANCELLED, None, None)
    if action == A.STATE_RECONCILED:
        require(state == S.BLOCKED, "INVALID_STATE_TRANSITION", "Only blocked tasks can reconcile")
        saved = task["runtime"].get("resume")
        require(bool(saved), "EVIDENCE_MISSING", "No known pre-block state")
        require(request.reconciliation_state == S(saved["state"]), "INVALID_STATE_TRANSITION", "Cannot invent a resumed stage")
        return Route(S(saved["state"]), R(saved["role"]) if saved["role"] else None,
                     P(saved["phase"]) if saved["phase"] else None)
    if action == A.GOVERNANCE_PATCH_COMPLETE:
        return Route(state, R(task["runtime"]["current_role"]) if task["runtime"]["current_role"] else None,
                     P(task["next_phase"]) if task.get("next_phase") else None)
    if action == A.REQUEST_IMPERIAL_CHECKPOINT_DECISION:
        require(task.get("task_type") == "GOVERNANCE_CHECKPOINT", "INVALID_STATE_TRANSITION", "Checkpoint contract required")
        return Route(state, R.EMPEROR, P.AWAITING_IMPERIAL_CHECKPOINT_DECISION)
    if action == A.ACCEPT_CHECKPOINT:
        require(task.get("task_type") == "GOVERNANCE_CHECKPOINT" and task.get("checkpoint_status") == "AUDIT_PASS",
                "EVIDENCE_MISSING", "Checkpoint AUDIT_PASS required")
        return Route(state, None, None)
    if action == A.RETURN_FOR_REMEDIATION:
        require(task.get("task_type") == "GOVERNANCE_CHECKPOINT", "INVALID_STATE_TRANSITION", "Checkpoint contract required")
        return Route(S.BLOCKED, R.PERSONNEL, P.EXECUTE)
    raise GovernanceError("INVALID_STATE_TRANSITION", f"No transition for {action}")


def validate_transition(current_state, action, target_state):
    """Pure fixed-edge check; dynamic edges use expected_route with the task contract."""
    require(action in FIXED and S(current_state) in FIXED[action][0]
            and S(target_state) == FIXED[action][1].state,
            "INVALID_STATE_TRANSITION", f"{current_state} / {action} / {target_state}")
