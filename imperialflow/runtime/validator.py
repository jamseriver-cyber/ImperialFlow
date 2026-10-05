from copy import deepcopy

from .errors import GovernanceError, require
from .evidence import artifact_bytes, verify_artifact, within_root
from .models import Action as A, EvidenceArtifact, EvidenceKind as K, ResultType as T, ResultValue as V, Role as R, TaskState as S
from .roles import validate_role_action
from .state_machine import BLOCKER_ACTIONS, EXECUTORS, expected_route


RESULTS = {
    A.START_TASK: (T.TASK_START, {V.GRANTED}),
    A.FORWARD_TO_ZHONGSHU: (T.INTAKE_RESULT, {V.COMPLETE}),
    A.FORWARD_TO_EXECUTOR: (T.INTAKE_RESULT, {V.COMPLETE}),
    A.REQUEST_MENXIA_REVIEW: (T.PLAN_RESULT, {V.COMPLETE}),
    A.APPROVE_PLAN: (T.REVIEW_RESULT, {V.APPROVE}),
    A.RETURN_FOR_REVISION: (T.REVIEW_RESULT, {V.REJECT}),
    A.REQUEST_IMPERIAL_AUTHORIZATION: (T.PACKAGE_RESULT, {V.COMPLETE}),
    A.APPROVE_EXECUTION: (T.IMPERIAL_DECISION, {V.APPROVE}),
    A.FORWARD_TO_NEXT_EXECUTOR: (T.EXECUTION_RESULT, {V.COMPLETE}),
    A.REQUEST_JUSTICE_VALIDATION: (T.EXECUTION_RESULT, {V.COMPLETE}),
    A.REQUEST_IMPERIAL_ACCEPTANCE: (T.VALIDATION_RESULT, {V.VALIDATION_PASS}),
    A.RETURN_FOR_CORRECTION: (T.VALIDATION_RESULT, {V.VALIDATION_FAIL}),
    A.ACCEPT_DELIVERY: (T.IMPERIAL_DECISION, {V.ACCEPTED}),
    A.GOVERNANCE_PATCH_COMPLETE: (T.GOVERNANCE_RESULT, {V.COMPLETE}),
    A.STATE_RECONCILED: (T.GOVERNANCE_RESULT, {V.COMPLETE}),
    A.IMPERIAL_INTERRUPT: (T.INTERRUPT_RESULT, {V.CHANGE_REQUEST}),
    A.CLASSIFY_INTERRUPT: (T.INTERRUPT_RESULT, {V.NOTE, V.CHANGE_REQUEST, V.NEW_TASK, V.HOLD, V.CANCEL, V.URGENT_FIX}),
    A.HOLD: (T.IMPERIAL_DECISION, {V.HOLD}),
    A.CANCEL: (T.IMPERIAL_DECISION, {V.CANCEL}),
    A.REQUEST_CHANGES: (T.IMPERIAL_DECISION, {V.CHANGES_REQUESTED}),
    A.ACCEPT_CHECKPOINT: (T.IMPERIAL_DECISION, {V.ACCEPTED}),
    A.REQUEST_IMPERIAL_CHECKPOINT_DECISION: (T.CHECKPOINT_AUDIT, {V.AUDIT_PASS, V.AUDIT_FINDINGS}),
    A.RETURN_FOR_REMEDIATION: (T.CHECKPOINT_AUDIT, {V.AUDIT_FINDINGS}),
}

STAGE_PROOF = {
    A.START_TASK: K.START_AUTHORIZATION,
    A.FORWARD_TO_ZHONGSHU: K.INTAKE,
    A.FORWARD_TO_EXECUTOR: K.INTAKE,
    A.REQUEST_MENXIA_REVIEW: K.PLAN,
    A.APPROVE_PLAN: K.REVIEW,
    A.RETURN_FOR_REVISION: K.REVIEW,
    A.REQUEST_IMPERIAL_AUTHORIZATION: K.EXECUTION_PACKAGE,
    A.APPROVE_EXECUTION: K.EXECUTION_AUTHORIZATION,
    A.FORWARD_TO_NEXT_EXECUTOR: K.DELIVERABLE,
    A.REQUEST_JUSTICE_VALIDATION: K.DELIVERABLE,
    A.REQUEST_IMPERIAL_ACCEPTANCE: K.VALIDATION,
    A.RETURN_FOR_CORRECTION: K.VALIDATION,
    A.ACCEPT_DELIVERY: K.ACCEPTANCE,
    A.GOVERNANCE_PATCH_COMPLETE: K.GOVERNANCE,
    A.STATE_RECONCILED: K.GOVERNANCE,
    A.REQUEST_IMPERIAL_CHECKPOINT_DECISION: K.CHECKPOINT,
    A.RETURN_FOR_REMEDIATION: K.CHECKPOINT,
    A.ACCEPT_CHECKPOINT: K.CHECKPOINT,
}


def gate(task, name, code):
    require(task.get(name, {}).get("status") in {"GRANTED", "APPROVED"}, code, name)


def validate_request(root, registry, request, invocation):
    validate_role_action(request.actor.role, request.action.type)
    require(request.actor == invocation.actor and request.invocation_id == invocation.id,
            "ROLE_MISMATCH", "Request does not match caller invocation")
    rt = registry["runtime"]
    require(request.expected_revision == rt["revision"], "STATE_CONFLICT", "Stale registry revision")
    task = next((t for t in registry["tasks"] if t["id"] == request.task_id), None)
    require(task is not None, "TASK_NOT_FOUND", request.task_id)
    live = rt["invocations"].get(invocation.id)
    require(live is not None and live["task_id"] == task["id"] and live["actor"] == invocation.actor.model_dump(mode="json"),
            "ROLE_MISMATCH", "No matching runtime-opened invocation")
    require(not live["finalized"], "INVOCATION_ALREADY_FINALIZED", invocation.id)
    require(not live.get("interrupted"), "STATE_CONFLICT", "Invocation was interrupted")
    action = request.action.type
    maintenance = action == A.GOVERNANCE_PATCH_COMPLETE and request.actor.role == R.PERSONNEL
    require(not live["maintenance"] or maintenance, "ROLE_CAPABILITY_VIOLATION", "Maintenance cannot move scientific state")
    require(not live["reconciliation"] or action == A.STATE_RECONCILED,
            "ROLE_CAPABILITY_VIOLATION", "Reconciliation context only permits STATE_RECONCILED")
    state = S(task["runtime"]["state"])
    require(state != S.DONE or maintenance, "TASK_ALREADY_DONE", task["id"])
    require(state not in {S.CANCELLED, S.VOID} or maintenance, "INVALID_STATE_TRANSITION", str(state))
    privileged = request.actor.role == R.EMPEROR or maintenance or (
        action == A.STATE_RECONCILED and request.actor.role == R.PERSONNEL)
    require(privileged or task["runtime"]["current_role"] == request.actor.role,
            "ROLE_MISMATCH", "Actor is not the currently routed role")
    if task.get("blockers") or state == S.BLOCKED:
        require(action in BLOCKER_ACTIONS | {A.STATE_RECONCILED, A.CLASSIFY_INTERRUPT, A.HOLD, A.CANCEL, A.IMPERIAL_INTERRUPT}
                or maintenance, "STATE_CONFLICT", "Scientific progress is blocked")
    if action != A.START_TASK and not maintenance:
        gate(task, "task_start_authorization", "TASK_START_AUTHORIZATION_MISSING")
    if action in {A.FORWARD_TO_NEXT_EXECUTOR, A.REQUEST_JUSTICE_VALIDATION, A.RETURN_FOR_CORRECTION,
                  A.REQUEST_IMPERIAL_ACCEPTANCE}:
        if task.get("imperial_authorization", {}).get("required", task["risk"] in {"HIGH", "CRITICAL"}):
            gate(task, "imperial_authorization", "IMPERIAL_AUTHORIZATION_MISSING")
    if action in RESULTS:
        kind, values = RESULTS[action]
        require(request.result.type == kind and request.result.value in values,
                "ACTION_RESULT_MISMATCH", action.value)
    elif action == A.RETURN_TO_ZHONGSHU:
        kind = T.VALIDATION_RESULT if request.actor.role == R.JUSTICE else T.IMPERIAL_DECISION
        require(request.result.type == kind and request.result.value in {V.VALIDATION_FAIL, V.CHANGES_REQUESTED},
                "ACTION_RESULT_MISMATCH", "Plan correction")
    else:
        require(request.result.type == T.BLOCKER and request.result.value in {V.BLOCKED, V.STATE_CONFLICT},
                "ACTION_RESULT_MISMATCH", "Blocker result required")

    catalogue = deepcopy(rt["evidence"])
    for artifact in request.artifacts:
        require(artifact.id not in catalogue, "STATE_CONFLICT", "Cannot replace historical evidence identifier")
        require(artifact.task_id == task["id"] and artifact.actor == invocation.actor,
                "ROLE_CAPABILITY_VIOLATION", "New evidence must be from this role and invocation identity")
        verify_artifact(root, artifact)
        if not maintenance:
            require(artifact.path == task["task_file"] or artifact.path.startswith("governance/evidence/"),
                    "ROLE_CAPABILITY_VIOLATION", "Stage evidence must be a governance record")
        if artifact.scope_paths or artifact.execution_roles:
            require(artifact.kind == K.EXECUTION_PACKAGE and artifact.actor.role == R.SHANGSHU,
                    "ROLE_CAPABILITY_VIOLATION", "Only SHANGSHU packages assign execution scope")
        catalogue[artifact.id] = artifact.model_dump(mode="json")
    require(bool(request.evidence_refs), "EVIDENCE_MISSING", "Evidence refs required")
    supplied = []
    for ref in request.evidence_refs:
        require(ref in catalogue, "EVIDENCE_MISSING", ref)
        artifact = EvidenceArtifact.model_validate(catalogue[ref])
        require(artifact.task_id == task["id"], "EVIDENCE_MISSING", "Cross-task evidence")
        verify_artifact(root, artifact)
        supplied.append(artifact)
    proof_kind = STAGE_PROOF.get(action, K.INTERRUPT if action in {A.IMPERIAL_INTERRUPT, A.CLASSIFY_INTERRUPT, A.HOLD, A.CANCEL, A.REQUEST_CHANGES} else K.GOVERNANCE)
    proofs = [a for a in supplied if a.kind == proof_kind and a.actor.role == request.actor.role]
    require(bool(proofs), "EVIDENCE_MISSING", f"{request.actor.role} {proof_kind}")
    proof = proofs[-1]
    bound = task["runtime"]

    def pinned(name, kind):
        ref = bound.get(name)
        require(ref in catalogue, "EVIDENCE_MISSING", name)
        item = EvidenceArtifact.model_validate(catalogue[ref])
        require(item.kind == kind and item.task_id == task["id"], "EVIDENCE_MISSING", name)
        verify_artifact(root, item)
        return item

    if action == A.START_TASK:
        content = artifact_bytes(root, proof).decode("utf-8")
        require(f"TASK_ID: {task['id']}" in content and "ACTION: START_TASK" in content
                and proof.actor.role == R.EMPEROR, "TASK_START_AUTHORIZATION_MISSING", "Direct task-bound START_TASK required")
    elif action not in {A.GOVERNANCE_PATCH_COMPLETE, A.STATE_RECONCILED} and not task["runtime"].get("history_only"):
        pinned("start_ref", K.START_AUTHORIZATION)
    if action in {A.APPROVE_PLAN, A.RETURN_FOR_REVISION}:
        plan = pinned("plan_ref", K.PLAN)
        require(proof.plan_ref == plan.id and proof.actor.identity != plan.actor.identity,
                "REVIEWER_INDEPENDENCE_VIOLATION", "Independent review must bind current plan")
    if action in {A.REQUEST_IMPERIAL_AUTHORIZATION, A.APPROVE_EXECUTION, A.FORWARD_TO_NEXT_EXECUTOR,
                  A.REQUEST_JUSTICE_VALIDATION, A.REQUEST_IMPERIAL_ACCEPTANCE, A.ACCEPT_DELIVERY}:
        if task["risk"] in {"HIGH", "CRITICAL"}:
            plan, review = pinned("plan_ref", K.PLAN), pinned("review_ref", K.REVIEW)
            require(review.plan_ref == plan.id and review.actor.identity != plan.actor.identity
                    and task.get("review_result") == "APPROVE", "EVIDENCE_MISSING", "Current independent plan approval")
            if action == A.REQUEST_IMPERIAL_AUTHORIZATION:
                require(proof.plan_ref == plan.id and bool(proof.execution_roles) and bool(proof.scope_paths),
                        "EVIDENCE_MISSING", "Package must bind plan, departments and exact write scope")
                require(all(r in EXECUTORS for r in proof.execution_roles) and len(set(proof.execution_roles)) == len(proof.execution_roles),
                        "ROLE_CAPABILITY_VIOLATION", "Invalid execution departments")
                for name in proof.scope_paths:
                    within_root(root, name)
            elif action != A.ACCEPT_DELIVERY:
                package = pinned("package_ref", K.EXECUTION_PACKAGE)
                require(package.plan_ref == plan.id, "EVIDENCE_MISSING", "Package is for a stale plan")
                if action == A.APPROVE_EXECUTION:
                    require(proof.plan_ref == plan.id and proof.package_ref == package.id,
                            "EVIDENCE_MISSING", "Emperor approval must bind specific plan and package")
                else:
                    authorization = pinned("authorization_ref", K.EXECUTION_AUTHORIZATION)
                    require(authorization.package_ref == package.id and authorization.plan_ref == plan.id,
                            "IMPERIAL_AUTHORIZATION_MISSING", "Approval is not for current package")
    if action == A.REQUEST_JUSTICE_VALIDATION:
        roles = bound.get("execution_roles", [])
        require(bool(roles) and roles[-1] == request.actor.role.value, "INVALID_STATE_TRANSITION", "Outstanding department handoffs")
        completed = bound.get("completed_roles", []) + [request.actor.role.value]
        require(all(role in completed for role in roles), "EVIDENCE_MISSING", "All department results required")
    if action in {A.REQUEST_IMPERIAL_ACCEPTANCE, A.RETURN_FOR_CORRECTION}:
        require(proof.plan_ref == bound.get("plan_ref"), "EVIDENCE_MISSING", "Validation must bind the current plan")
        deliverables = [EvidenceArtifact.model_validate(catalogue[ref]) for ref in bound.get("deliverable_refs", [])]
        require(bool(deliverables), "EVIDENCE_MISSING", "Delivery evidence")
        for artifact in deliverables:
            verify_artifact(root, artifact)
        require(all(a.actor.identity != proof.actor.identity for a in deliverables),
                "REVIEWER_INDEPENDENCE_VIOLATION", "Validator cannot validate own delivery")
    if action == A.ACCEPT_DELIVERY:
        require(task.get("validation_status") == "VALIDATION_PASS" and proof.plan_ref == bound.get("plan_ref"),
                "IMPERIAL_ACCEPTANCE_MISSING", "Actual validation and task-bound acceptance required")
        validation = pinned("validation_ref", K.VALIDATION)
        require(proof.validation_ref == validation.id and validation.plan_ref == bound.get("plan_ref"),
                "IMPERIAL_ACCEPTANCE_MISSING", "Acceptance must bind actual current validation")
    if action == A.STATE_RECONCILED:
        # Cannot use recovery to bypass evidence-bound execution gates.
        saved = bound.get("resume", {})
        if saved.get("state") in {S.EXECUTION, S.VALIDATION, S.AWAITING_IMPERIAL_ACCEPTANCE}:
            gate(task, "imperial_authorization", "IMPERIAL_AUTHORIZATION_MISSING")
            pinned("authorization_ref", K.EXECUTION_AUTHORIZATION)
    if action == A.CLASSIFY_INTERRUPT:
        require(request.interrupt is not None and request.result.value.value == request.interrupt.classification,
                "ACTION_RESULT_MISMATCH", "Classification must equal typed result")
    route = expected_route(task, request)
    require(request.target_state == route.state and request.routing.next_role == route.role
            and request.routing.next_phase == route.phase,
            "INVALID_STATE_TRANSITION", "Action, target state and routing disagree")
    budgets = task["execution_budget"]
    counters = bound.get("counters", {})
    counters_to_increment = {
        A.RETURN_FOR_REVISION: ["revisions", "review_rounds"],
        A.RETURN_FOR_CORRECTION: ["execution_retries"], A.APPROVE_PLAN: ["review_rounds"],
        A.REQUEST_CHANGES: ["revisions"], A.RETURN_TO_ZHONGSHU: ["revisions"],
    }.get(action, [])
    if action == A.CLASSIFY_INTERRUPT and route.state == S.CHANGES_REQUESTED:
        counters_to_increment = ["revisions"]
    for name in counters_to_increment:
        require(counters.get(name, 0) < budgets["max_" + name], "BUDGET_EXCEEDED", name)
    return task, route, catalogue, proof, maintenance, counters_to_increment
