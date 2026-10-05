"""Single-writer registry, fail-closed validation and recoverable local commits."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from pydantic import ValidationError
import yaml

from .errors import GovernanceError, require
from .evidence import digest, verify_artifact, within_root
from .models import Action as A, EvidenceArtifact, Invocation, Role as R, TaskState as S, TransitionRequest
from .trace import canonical_json, seal_event, timestamp
from .validator import validate_request, gate
from .views import render_current_state


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        require(key not in result, "STATE_CONFLICT", f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_registry(raw):
    try:
        data = yaml.load(raw, Loader=UniqueLoader)
    except yaml.YAMLError as error:
        raise GovernanceError("STATE_CONFLICT", str(error)) from error
    require(isinstance(data, dict) and isinstance(data.get("tasks"), list), "STATE_CONFLICT", "Registry structure")
    ids = [t["id"] for t in data["tasks"]]
    require(len(ids) == len(set(ids)), "STATE_CONFLICT", "Duplicate task IDs")
    return data


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".runtime-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Runtime:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.registry_path = self.root / "governance/TASK_REGISTRY.yaml"
        self.view_path = self.root / "governance/CURRENT_STATE.md"
        self.journal_path = self.root / "governance/.runtime-pending.json"
        self.lock_path = self.root / "governance/.runtime.lock"

    @contextmanager
    def lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise GovernanceError("STATE_CONFLICT", "Another writer or stale runtime lock") from error
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(str(os.getpid()))
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

    def load(self, check_view=True):
        require(not self.journal_path.exists(), "STATE_CONFLICT", "Interrupted commit: run recover before any new action")
        raw = self.registry_path.read_bytes()
        registry = parse_registry(raw)
        require("runtime" in registry and registry["runtime"].get("protocol_version") == 1,
                "STATE_CONFLICT", "Registry not migrated to V1")
        rt = registry["runtime"]
        previous = None
        for seq in range(1, rt["trace_seq"] + 1):
            path = self.root / f"governance/traces/{seq:06d}.json"
            require(path.is_file(), "STATE_CONFLICT", "Missing trace")
            event = json.loads(path.read_text(encoding="utf-8"))
            seal = event.pop("event_sha256")
            require(event["sequence"] == seq and seal == digest(canonical_json(event).encode("utf-8")) and event["previous_event_sha256"] == previous,
                    "STATE_CONFLICT", "Broken trace chain")
            previous = seal
        require(rt["trace_seq"] > 0 and event["registry_sha256"] == digest(raw),
                "STATE_CONFLICT", "Registry modified outside Runtime")
        if check_view:
            require(self.view_path.exists() and self.view_path.read_bytes() == render_current_state(registry).encode("utf-8"),
                    "STATE_CONFLICT", "CURRENT_STATE is stale or edited; use render")
        return registry

    def _commit(self, before_raw, registry, event, evidence_path=None, evidence_append=""):
        require(self.registry_path.read_bytes() == before_raw, "STATE_CONFLICT", "Concurrent registry write")
        require(not self.journal_path.exists(), "STATE_CONFLICT", "Unfinished commit")
        seq = registry["runtime"]["trace_seq"] + 1
        registry["runtime"]["trace_seq"] = seq
        registry["runtime"]["revision"] += 1
        registry["runtime"]["updated_at"] = timestamp()
        after = yaml.safe_dump(registry, allow_unicode=True, sort_keys=False).encode("utf-8")
        previous = None
        if seq > 1:
            previous = json.loads((self.root / f"governance/traces/{seq-1:06d}.json").read_text(encoding="utf-8"))["event_sha256"]
        event = seal_event({**event, "sequence": seq, "timestamp": registry["runtime"]["updated_at"],
                            "registry_sha256": digest(after), "previous_event_sha256": previous})
        evidence_before = ""
        if evidence_path:
            evidence_file = within_root(self.root, evidence_path)
            evidence_before = evidence_file.read_text(encoding="utf-8") if evidence_file.exists() else ""
        journal = {
            "before_sha256": digest(before_raw), "after_sha256": digest(after),
            "registry_after": after.decode("utf-8"), "event": event,
            "evidence_path": evidence_path, "evidence_before": evidence_before,
            "evidence_after": evidence_before + evidence_append,
            "view_after": render_current_state(registry),
        }
        atomic_write(self.journal_path, json.dumps(journal, ensure_ascii=False).encode("utf-8"))
        self._finish(journal)
        return event

    def _finish(self, journal):
        current = digest(self.registry_path.read_bytes())
        require(current in {journal["before_sha256"], journal["after_sha256"]}, "STATE_CONFLICT", "Recovery would overwrite external changes")
        if current != journal["after_sha256"]:
            atomic_write(self.registry_path, journal["registry_after"].encode("utf-8"))
        event = journal["event"]
        trace_path = self.root / f"governance/traces/{event['sequence']:06d}.json"
        trace_bytes = (json.dumps(event, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if trace_path.exists():
            require(trace_path.read_bytes() == trace_bytes, "STATE_CONFLICT", "Trace is append-only")
        else:
            atomic_write(trace_path, trace_bytes)
        if journal["evidence_path"]:
            path = within_root(self.root, journal["evidence_path"])
            actual = path.read_text(encoding="utf-8") if path.exists() else ""
            require(actual in {journal["evidence_before"], journal["evidence_after"]},
                    "STATE_CONFLICT", "Task evidence concurrently changed")
            if actual != journal["evidence_after"]:
                # Append only; historical bytes are never rewritten.
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("ab") as stream:
                    stream.write(journal["evidence_after"][len(journal["evidence_before"]):].encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
        atomic_write(self.view_path, journal["view_after"].encode("utf-8"))
        self.journal_path.unlink()

    def recover(self):
        with self.lock():
            require(self.journal_path.exists(), "STATE_CONFLICT", "No pending transaction")
            journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
            require(digest(journal["registry_after"].encode("utf-8")) == journal["after_sha256"],
                    "STATE_CONFLICT", "Corrupt pending registry")
            self._finish(journal)
        return self.load()

    def render(self):
        with self.lock():
            registry = self.load(check_view=False)
            atomic_write(self.view_path, render_current_state(registry).encode("utf-8"))

    def bootstrap(self, metadata, evidence, expected_sha256):
        """One authorized migration, preserving every legacy task field."""
        with self.lock():
            before = self.registry_path.read_bytes()
            require(digest(before) == expected_sha256, "STATE_CONFLICT", "Migration snapshot changed")
            registry = parse_registry(before)
            require("runtime" not in registry, "STATE_CONFLICT", "Already migrated")
            catalogue = {}
            for item in evidence:
                artifact = EvidenceArtifact.model_validate(item)
                if artifact.status == "VALID":
                    verify_artifact(self.root, artifact)
                require(artifact.id not in catalogue, "STATE_CONFLICT", "Duplicate migrated artifact")
                catalogue[artifact.id] = artifact.model_dump(mode="json")
            for task in registry["tasks"]:
                details = metadata[task["id"]]
                task["runtime"] = deepcopy(details)
                task["execution_budget"] = {"max_revisions": 2, "max_review_rounds": 2, "max_execution_retries": 2}
                if task["status"] == "DONE":
                    require(details["state"] == "DONE", "STATE_CONFLICT", "Historical completion changed")
                elif details["state"] == "EXECUTION":
                    gate(task, "task_start_authorization", "TASK_START_AUTHORIZATION_MISSING")
                    gate(task, "imperial_authorization", "IMPERIAL_AUTHORIZATION_MISSING")
                    for key in ("plan_ref", "review_ref", "package_ref", "authorization_ref", "start_ref"):
                        require(details.get(key) in catalogue, "EVIDENCE_MISSING", key)
                require(details.get("current_role") == task.get("next_role"), "ROLE_MISMATCH", "Migration must preserve scientific routing")
            registry["runtime"] = {"protocol_version": 1, "revision": 0, "trace_seq": 0,
                                    "evidence": catalogue, "invocations": {}, "maintenance_last_action": None}
            return self._commit(before, registry, {"kind": "MIGRATION", "task_id": registry["current_task"],
                "actor": {"role": "PERSONNEL", "identity": "imperialflow-v1-migration"},
                "previous_state": None, "next_state": metadata[registry["current_task"]]["state"],
                "result": "LEGACY_STATE_PRESERVED", "action": None,
                "next_role": metadata[registry["current_task"]]["current_role"],
                "evidence_refs": list(catalogue), "validator_result": "ALLOW"})

    def begin(self, task_id, invocation: Invocation, maintenance=False, reconciliation=False):
        with self.lock():
            before = self.registry_path.read_bytes()
            registry = self.load()
            require(invocation.id not in registry["runtime"]["invocations"], "INVOCATION_ALREADY_FINALIZED", invocation.id)
            task = next((t for t in registry["tasks"] if t["id"] == task_id), None)
            require(task is not None, "TASK_NOT_FOUND", task_id)
            state = S(task["runtime"]["state"])
            if maintenance or reconciliation:
                require(invocation.actor.role == R.PERSONNEL, "ROLE_MISMATCH", "PERSONNEL context required")
                require(not reconciliation or state == S.BLOCKED, "INVALID_STATE_TRANSITION", "Not blocked")
            else:
                require(state not in {S.DONE, S.CANCELLED, S.VOID}, "TASK_ALREADY_DONE", task_id)
                require(invocation.actor.role == R.EMPEROR or task["runtime"]["current_role"] == invocation.actor.role,
                        "ROLE_MISMATCH", "Caller not routed")
                if invocation.actor.role != R.EMPEROR:
                    gate(task, "task_start_authorization", "TASK_START_AUTHORIZATION_MISSING")
                if state == S.EXECUTION and invocation.actor.role in {R.WAR, R.RITES, R.REVENUE, R.WORKS}:
                    if task.get("imperial_authorization", {}).get("required", True):
                        gate(task, "imperial_authorization", "IMPERIAL_AUTHORIZATION_MISSING")
                if state == S.AUTHORIZED and invocation.actor.role == R.PRINCE:
                    task["runtime"]["state"] = S.INTAKE.value
            active = [i for i in registry["runtime"]["invocations"].values()
                      if i["task_id"] == task_id and not i["finalized"] and not i.get("interrupted")]
            require(not active or invocation.actor.role == R.EMPEROR or maintenance or reconciliation,
                    "INVOCATION_ACTIVE", "A role invocation is still open")
            registry["runtime"]["invocations"][invocation.id] = {
                "task_id": task_id, "actor": invocation.actor.model_dump(mode="json"),
                "finalized": False, "maintenance": maintenance, "reconciliation": reconciliation,
            }
            event = self._commit(before, registry, {"kind": "INVOCATION_OPEN", "task_id": task_id,
                "actor": invocation.actor.model_dump(mode="json"), "previous_state": state.value,
                "next_state": task["runtime"]["state"], "result": "ROLE_CONTEXT_OPENED", "action": None,
                "next_role": task.get("next_role"), "evidence_refs": [], "validator_result": "ALLOW"})
            return event

    @staticmethod
    def parse_request(data):
        try:
            return TransitionRequest.model_validate(data)
        except ValidationError as error:
            raise GovernanceError("SCHEMA_VALIDATION_FAILED", str(error)) from error

    def check(self, data, invocation):
        request = self.parse_request(data)
        registry = self.load()
        validate_request(self.root, registry, request, invocation)
        return {"validator_result": "ALLOW", "target_state": request.target_state.value,
                "registry_revision": registry["runtime"]["revision"]}

    def submit(self, data, invocation):
        request = self.parse_request(data)
        with self.lock():
            before = self.registry_path.read_bytes()
            registry = self.load()
            task, route, catalogue, proof, maintenance, counter = validate_request(self.root, registry, request, invocation)
            live = registry["runtime"]["invocations"][invocation.id]
            previous = task["runtime"]["state"]
            if maintenance:
                registry["runtime"]["maintenance_last_action"] = request.model_dump(mode="json")
            else:
                self._apply(task, request, proof, route, counter)
                if request.action.type == A.ACCEPT_DELIVERY:
                    registry["last_completed_task"] = task["id"]
            registry["runtime"]["evidence"] = catalogue
            live["finalized"] = True
            live["request_id"] = request.request_id
            if request.action.type in {A.HOLD, A.CANCEL, A.IMPERIAL_INTERRUPT}:
                for key, item in registry["runtime"]["invocations"].items():
                    if key != invocation.id and item["task_id"] == task["id"] and not item["finalized"]:
                        item["interrupted"] = True
            event = {"kind": "GOVERNANCE_MAINTENANCE" if maintenance else "TRANSITION", "task_id": task["id"],
                "invocation_id": invocation.id, "request_id": request.request_id,
                "actor": request.actor.model_dump(mode="json"), "previous_state": previous,
                "result": request.result.model_dump(mode="json"), "action": request.action.type.value,
                "next_state": task["runtime"]["state"], "next_role": task.get("next_role"),
                "next_phase": task.get("next_phase"), "plan_ref": task["runtime"].get("plan_ref"),
                "evidence_refs": request.evidence_refs, "validator_result": "ALLOW"}
            block = ("\n\n## ImperialFlow V1 Runtime Commit\n\n```json\n"
                     + json.dumps(request.model_dump(mode="json"), ensure_ascii=False, indent=2)
                     + "\n```\n\nRuntime Validator: ALLOW. 科学状态以 Canonical Registry 为准。\n")
            # Governance maintenance belongs in its own record, not the science task history.
            evidence_path = "governance/upgrades/imperialflow_v1.md" if maintenance else task["task_file"]
            return self._commit(before, registry, event, evidence_path, block)

    @staticmethod
    def _apply(task, request, proof, route, counter):
        rt = task["runtime"]
        action = request.action.type
        if route.state == S.BLOCKED and rt["state"] != S.BLOCKED:
            rt["resume"] = {"state": rt["state"], "role": task.get("next_role"), "phase": task.get("next_phase"),
                            "status": task["status"], "legacy_phase": task.get("phase")}
        if action == A.STATE_RECONCILED or (action == A.CLASSIFY_INTERRUPT and request.interrupt.classification in {"NOTE", "NEW_TASK"}):
            saved = rt["resume"]
            task["status"], task["phase"] = saved["status"], saved["legacy_phase"]
            task["blockers"] = []
        else:
            status = {S.AUTHORIZED: "PLANNED", S.PLAN: "PLANNED", S.REVIEW: "READY_FOR_REVIEW",
                      S.EXECUTION_PREP: "REVIEW_APPROVED", S.AWAITING_IMPERIAL_AUTHORIZATION: "AWAITING_IMPERIAL_AUTHORIZATION",
                      S.EXECUTION: "IN_PROGRESS", S.VALIDATION: "READY_FOR_VALIDATION",
                      S.AWAITING_IMPERIAL_ACCEPTANCE: "AWAITING_IMPERIAL_ACCEPTANCE", S.DONE: "DONE",
                      S.BLOCKED: "BLOCKED", S.CHANGES_REQUESTED: "CHANGES_REQUESTED", S.CANCELLED: "CANCELLED"}
            task["status"] = status.get(route.state, task["status"])
        rt["state"], rt["current_role"] = route.state.value, route.role.value if route.role else None
        task["next_role"], task["next_phase"] = rt["current_role"], route.phase.value if route.phase else None
        next_actions = {R.PRINCE: "PRINCE_INTAKE", R.ZHONGSHU: "PLAN", R.MENXIA: "MENXIA_REVIEW",
                        R.SHANGSHU: "EXECUTION_PREPARATION", R.JUSTICE: "JUSTICE_VALIDATE"}
        task["next_action"] = next_actions.get(route.role, f"{route.role.value}_EXECUTE" if route.role else None)
        if route.role == R.EMPEROR:
            task["next_action"] = route.phase.value if route.phase else "IMPERIAL_DECISION"
        task["last_action"] = {"actor": request.actor.role.value, "action": action.value}
        if route.state == S.BLOCKED:
            task["blockers"] = [request.result.value.value]
        if counter:
            counters = rt.setdefault("counters", {})
            for name in counter:
                counters[name] = counters.get(name, 0) + 1
            task["rework_rounds"] = counters.get("revisions", 0)
        if action == A.START_TASK:
            task["task_start_authorization"] = {"required": True, "status": "GRANTED"}
            rt["start_ref"] = proof.id
        elif action in {A.FORWARD_TO_ZHONGSHU, A.FORWARD_TO_EXECUTOR}:
            task["intake_status"] = "COMPLETE"
        elif action == A.REQUEST_MENXIA_REVIEW:
            task["phase"] = "PLAN"
            task["plan_revision"] = (task.get("plan_revision") or 0) + 1
            rt["plan_ref"] = proof.id
        elif action == A.APPROVE_PLAN:
            task["phase"], task["review_result"] = "REVIEW", "APPROVE"
            rt["review_ref"] = proof.id
        elif action == A.REQUEST_IMPERIAL_AUTHORIZATION:
            task["execution_preparation"], task["execution_package"] = "COMPLETE", "READY"
            task["imperial_authorization"] = {"required": True, "status": "PENDING"}
            rt["package_ref"] = proof.id
            rt["execution_roles"] = [role.value for role in proof.execution_roles]
            rt["scope_paths"] = proof.scope_paths
        elif action == A.APPROVE_EXECUTION:
            task["imperial_authorization"] = {"required": True, "status": "APPROVED"}
            task["status"] = "REVIEW_APPROVED"
            rt["authorization_ref"] = proof.id
        elif action in {A.FORWARD_TO_NEXT_EXECUTOR, A.REQUEST_JUSTICE_VALIDATION}:
            task["phase"], task["execution_status"] = "EXECUTE", "IN_PROGRESS"
            rt.setdefault("completed_roles", []).append(request.actor.role.value)
            rt.setdefault("deliverable_refs", []).append(proof.id)
            if action == A.REQUEST_JUSTICE_VALIDATION:
                task["execution_status"] = "COMPLETE"
        elif action == A.REQUEST_IMPERIAL_ACCEPTANCE:
            task["validation_status"] = "VALIDATION_PASS"
            task["imperial_acceptance"] = {"required": True, "status": "PENDING"}
            rt["validation_ref"] = proof.id
        elif action == A.RETURN_FOR_CORRECTION:
            task["validation_status"] = "VALIDATION_FAIL"
            task["execution_status"] = "IN_PROGRESS"
            rt["completed_roles"] = []
            rt["deliverable_refs"] = []
        elif action == A.ACCEPT_DELIVERY:
            task["imperial_acceptance"] = {"required": True, "status": "ACCEPTED"}
            rt["acceptance_ref"] = proof.id
        elif action == A.REQUEST_IMPERIAL_CHECKPOINT_DECISION:
            task["checkpoint_status"] = request.result.value.value
            rt["checkpoint_ref"] = proof.id
        elif action == A.ACCEPT_CHECKPOINT:
            task["checkpoint_acceptance"] = "ACCEPTED"
        if action in {A.RETURN_FOR_REVISION, A.RETURN_TO_ZHONGSHU, A.REQUEST_CHANGES} or (action == A.CLASSIFY_INTERRUPT and route.state == S.CHANGES_REQUESTED):
            task["review_result"] = None
            task["execution_preparation"], task["execution_package"] = "NOT_STARTED", "NOT_READY"
            task["imperial_authorization"] = {"required": True, "status": "NOT_REQUESTED"}
            task["imperial_acceptance"] = {"required": True, "status": "NOT_REQUESTED"}
            task["validation_status"] = "NOT_RUN"
            for key in ("review_ref", "package_ref", "authorization_ref", "validation_ref"):
                rt.pop(key, None)
        if action == A.IMPERIAL_INTERRUPT:
            rt["interrupt_pending"] = True
        if action == A.CLASSIFY_INTERRUPT:
            rt["interrupt_pending"] = False
            rt.setdefault("interrupts", []).append(request.interrupt.model_dump(mode="json"))
