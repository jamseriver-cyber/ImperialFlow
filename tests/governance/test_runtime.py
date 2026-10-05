"""Governance EVALs operate only on synthetic temporary registries."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from imperialflow.runtime import Invocation, Runtime
from imperialflow.runtime.errors import GovernanceError
from imperialflow.runtime.evidence import digest
from imperialflow.runtime.models import EvidenceArtifact, Role, TaskState, TransitionRequest
from imperialflow.runtime.roles import CAPABILITIES, validate_role_action
from imperialflow.runtime.state_machine import validate_transition
from imperialflow.runtime.views import render_current_state


class RuntimeEvals(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        self.number = 0

    def artifact(self, kind, role, *, identifier=None, status="VALID", content=None, **fields):
        self.number += 1
        identifier = identifier or f"artifact-{self.number}"
        content = content or f"Fixture evidence {kind} by {role}\n"
        path = f"governance/evidence/{identifier}.md"
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return EvidenceArtifact.model_validate({"id": identifier, "task_id": "TEST-T01", "kind": kind,
            "status": status, "path": path, "sha256": digest(file.read_bytes()),
            "actor": {"role": role, "identity": role.lower() + "-fixture"}, **fields}).model_dump(mode="json")

    def seed(self, state="NOT_STARTED", role="EMPEROR", *, authorized=True, execution_authorized=True, blocked=False, counters=None, task_type=None):
        proofs = [
            self.artifact("START_AUTHORIZATION", "EMPEROR", identifier="start", content="ACTION: START_TASK\nTASK_ID: TEST-T01\n"),
            self.artifact("PLAN", "ZHONGSHU", identifier="plan"),
            self.artifact("REVIEW", "MENXIA", identifier="review", plan_ref="plan"),
            self.artifact("EXECUTION_PACKAGE", "SHANGSHU", identifier="package", plan_ref="plan",
                          scope_paths=["src/test-model.py", "docs/test-model.md"], execution_roles=["WAR", "RITES"]),
            self.artifact("EXECUTION_AUTHORIZATION", "EMPEROR", identifier="authorization", plan_ref="plan", package_ref="package"),
            self.artifact("DELIVERABLE", "WAR", identifier="war-delivery"),
            self.artifact("DELIVERABLE", "RITES", identifier="rites-delivery"),
            self.artifact("VALIDATION", "JUSTICE", identifier="validation", plan_ref="plan"),
            self.artifact("PLAN", "ZHONGSHU", identifier="void-plan", status="VOID"),
        ]
        task = {"id": "TEST-T01", "title": "Governance synthetic fixture", "version": "V0", "risk": "HIGH",
            "phase": None, "status": "DONE" if state == "DONE" else "PLANNED", "plan_revision": 1,
            "rework_rounds": 0, "task_file": "governance/tasks/TEST-T01.md", "next_role": role,
            "next_phase": "EXECUTE" if state == "EXECUTION" else None, "next_action": None,
            "task_start_authorization": {"required": True, "status": "GRANTED" if authorized else "NOT_GRANTED"},
            "intake_status": "COMPLETE", "review_result": "APPROVE", "execution_preparation": "COMPLETE",
            "execution_package": "READY", "execution_status": "NOT_STARTED", "validation_status": "NOT_RUN",
            "imperial_authorization": {"required": True, "status": "APPROVED" if execution_authorized else "NOT_REQUESTED"},
            "imperial_acceptance": {"required": True, "status": "NOT_REQUESTED"},
            "last_action": None, "blockers": ["STATE_CONFLICT"] if blocked else []}
        registry = {"schema_version": 1, "project": "TEST", "current_version": "V0", "current_task": "TEST-T01",
                    "last_completed_task": None, "tasks": [task]}
        rt = {"state": state, "current_role": role, "start_ref": "start", "plan_ref": "plan", "review_ref": "review",
              "package_ref": "package", "authorization_ref": "authorization", "validation_ref": "validation",
              "execution_roles": ["WAR", "RITES"], "completed_roles": ["WAR", "RITES"],
              "deliverable_refs": ["war-delivery", "rites-delivery"], "counters": counters or {}}
        if task_type:
            task["task_type"] = task_type
        file = self.runtime.registry_path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
        self.runtime.bootstrap({"TEST-T01": rt}, proofs, digest(file.read_bytes()))

    def context(self, role, *, maintenance=False, reconciliation=False):
        self.number += 1
        context = Invocation.model_validate({"id": f"invocation-{self.number}", "actor": {"role": role, "identity": role.lower() + "-fixture"}})
        self.runtime.begin("TEST-T01", context, maintenance, reconciliation)
        return context

    def request(self, context, action, state, role, phase, kind, result_type, value, **fields):
        proof = self.artifact(kind, context.actor.role.value, **fields)
        return {"protocol_version": 1, "request_id": "request-" + context.id, "invocation_id": context.id,
                "task_id": "TEST-T01", "expected_revision": self.runtime.load()["runtime"]["revision"],
                "actor": context.actor.model_dump(mode="json"), "action": {"type": action},
                "target_state": state, "routing": {"next_role": role, "next_phase": phase},
                "result": {"type": result_type, "value": value}, "evidence_refs": [proof["id"]], "artifacts": [proof]}

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def denied(self, code, operation):
        before = self.snapshot()
        with self.assertRaises(GovernanceError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.snapshot(), before, "DENY must not write state, trace, evidence or view")

    def test_eval_001_next_task_is_not_start_task(self):
        self.seed(authorized=False)
        ctx = self.context("EMPEROR")
        req = self.request(ctx, "START_TASK", "AUTHORIZED", "PRINCE", "INTAKE", "START_AUTHORIZATION", "TASK_START", "GRANTED", content="NEXT_TASK: TEST-T01\n")
        self.denied("TASK_START_AUTHORIZATION_MISSING", lambda: self.runtime.submit(req, ctx))

    def test_eval_002_prince_cannot_create_or_approve_plan(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "APPROVE_PLAN", "EXECUTION_PREP", "SHANGSHU", "EXECUTION_PREP", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        self.denied("ROLE_CAPABILITY_VIOLATION", lambda: self.runtime.submit(req, ctx))
        self.denied("ROLE_CAPABILITY_VIOLATION", lambda: validate_role_action("PRINCE", "CREATE_PLAN"))

    def test_eval_003_intake_requires_start_task(self):
        self.seed("AUTHORIZED", "PRINCE", authorized=False)
        ctx = Invocation.model_validate({"id": "missing-start", "actor": {"role": "PRINCE", "identity": "prince-fixture"}})
        self.denied("TASK_START_AUTHORIZATION_MISSING", lambda: self.runtime.begin("TEST-T01", ctx))

    def test_eval_004_menxia_cannot_own_execution_prep(self):
        self.seed("REVIEW", "MENXIA")
        ctx = self.context("MENXIA")
        req = self.request(ctx, "APPROVE_PLAN", "EXECUTION_PREP", "MENXIA", "EXECUTION_PREP", "REVIEW", "REVIEW_RESULT", "APPROVE", plan_ref="plan")
        self.denied("INVALID_STATE_TRANSITION", lambda: self.runtime.submit(req, ctx))

    def test_eval_005_war_requires_approve_execution(self):
        # Migration itself refuses to import a purported execution state without authorization.
        before = self.snapshot()
        with self.assertRaises(GovernanceError) as caught:
            self.seed("EXECUTION", "WAR", execution_authorized=False)
        self.assertEqual(caught.exception.code, "IMPERIAL_AUTHORIZATION_MISSING")
        self.assertFalse((self.root / "governance/traces").exists())
        self.assertFalse(self.runtime.view_path.exists())

    def test_eval_006_validation_pass_is_not_done(self):
        self.seed("VALIDATION", "JUSTICE")
        ctx = self.context("JUSTICE")
        req = self.request(ctx, "REQUEST_IMPERIAL_ACCEPTANCE", "AWAITING_IMPERIAL_ACCEPTANCE", "EMPEROR", "AWAITING_IMPERIAL_ACCEPTANCE", "VALIDATION", "VALIDATION_RESULT", "VALIDATION_PASS", plan_ref="plan")
        self.runtime.submit(req, ctx)
        task = self.runtime.load()["tasks"][0]
        self.assertEqual(task["runtime"]["state"], "AWAITING_IMPERIAL_ACCEPTANCE")
        self.assertEqual(task["imperial_acceptance"]["status"], "PENDING")
        self.assertNotEqual(task["status"], "DONE")

    def test_eval_007_void_plan_cannot_be_execution_input(self):
        self.seed("EXECUTION", "WAR")
        ctx = self.context("WAR")
        req = self.request(ctx, "FORWARD_TO_NEXT_EXECUTOR", "EXECUTION", "RITES", "EXECUTE", "DELIVERABLE", "EXECUTION_RESULT", "COMPLETE")
        req["evidence_refs"].append("void-plan")
        self.denied("VOID_ARTIFACT_REFERENCE", lambda: self.runtime.submit(req, ctx))

    def test_eval_008_one_final_action_per_invocation(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        self.runtime.submit(req, ctx)
        req["expected_revision"] = self.runtime.load()["runtime"]["revision"]
        self.denied("INVOCATION_ALREADY_FINALIZED", lambda: self.runtime.submit(req, ctx))
        req["action"] = [{"type": "FORWARD_TO_ZHONGSHU"}, {"type": "REQUEST_MENXIA_REVIEW"}]
        self.denied("SCHEMA_VALIDATION_FAILED", lambda: self.runtime.submit(req, ctx))

    def test_eval_009_whitelist_denies_illegal_role_action(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "ACCEPT_DELIVERY", "DONE", None, None, "INTAKE", "INTAKE_RESULT", "COMPLETE")
        self.denied("ROLE_CAPABILITY_VIOLATION", lambda: self.runtime.submit(req, ctx))

    def test_eval_010_action_and_next_role_must_agree(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "WAR", "EXECUTE", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        self.denied("INVALID_STATE_TRANSITION", lambda: self.runtime.submit(req, ctx))

    def test_eval_011_current_state_is_derived(self):
        self.seed()
        expected = render_current_state(self.runtime.load())
        self.assertEqual(self.runtime.view_path.read_text(encoding="utf-8"), expected)
        self.runtime.view_path.write_text("STATUS: DONE\n", encoding="utf-8")
        self.denied("STATE_CONFLICT", self.runtime.load)
        self.runtime.render()
        self.assertEqual(self.runtime.view_path.read_text(encoding="utf-8"), expected)

    def test_eval_012_state_conflict_blocks_scientific_progress(self):
        self.seed("PLAN", "ZHONGSHU", blocked=True)
        ctx = self.context("ZHONGSHU")
        req = self.request(ctx, "REQUEST_MENXIA_REVIEW", "REVIEW", "MENXIA", "REVIEW", "PLAN", "PLAN_RESULT", "COMPLETE")
        self.denied("STATE_CONFLICT", lambda: self.runtime.submit(req, ctx))

    def test_start_then_independent_intake_and_legal_trace(self):
        self.seed(authorized=False)
        ctx = self.context("EMPEROR")
        req = self.request(ctx, "START_TASK", "AUTHORIZED", "PRINCE", "INTAKE", "START_AUTHORIZATION", "TASK_START", "GRANTED", content="ACTION: START_TASK\nTASK_ID: TEST-T01\n")
        event = self.runtime.submit(req, ctx)
        self.assertEqual(event["previous_state"], "NOT_STARTED")
        self.assertEqual(event["next_state"], "AUTHORIZED")
        self.assertEqual(event["validator_result"], "ALLOW")
        ctx = self.context("PRINCE")
        self.assertEqual(self.runtime.load()["tasks"][0]["runtime"]["state"], "INTAKE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        self.runtime.submit(req, ctx)
        self.assertEqual(self.runtime.load()["tasks"][0]["runtime"]["current_role"], "ZHONGSHU")

    def test_role_matrix_and_fixed_state_machine_are_executable(self):
        self.assertEqual(set(CAPABILITIES), {r.value for r in Role})
        for role, actions in CAPABILITIES.items():
            for action in actions:
                validate_role_action(role, action)
        validate_transition("INTAKE", "FORWARD_TO_ZHONGSHU", "PLAN")
        with self.assertRaises(GovernanceError):
            validate_transition("INTAKE", "FORWARD_TO_ZHONGSHU", "DONE")

    def test_dry_run_no_writes_and_stale_revision_denied(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        before = self.snapshot()
        self.assertEqual(self.runtime.check(req, ctx)["validator_result"], "ALLOW")
        self.assertEqual(self.snapshot(), before)
        req["expected_revision"] -= 1
        self.denied("STATE_CONFLICT", lambda: self.runtime.submit(req, ctx))

    def test_identity_and_evidence_tampering_denied(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        wrong = deepcopy(req)
        wrong["actor"]["identity"] = "imposter"
        self.denied("ROLE_MISMATCH", lambda: self.runtime.submit(wrong, ctx))
        (self.root / req["artifacts"][0]["path"]).write_text("tampered", encoding="utf-8")
        self.denied("STATE_CONFLICT", lambda: self.runtime.submit(req, ctx))

    def test_reviewer_independence_is_enforced(self):
        self.seed("REVIEW", "MENXIA")
        ctx = self.context("MENXIA")
        req = self.request(ctx, "APPROVE_PLAN", "EXECUTION_PREP", "SHANGSHU", "EXECUTION_PREP", "REVIEW", "REVIEW_RESULT", "APPROVE", plan_ref="plan")
        # Launch context identity equals the plan author's identity: role label is insufficient.
        changed = ctx.model_copy(update={"actor": ctx.actor.model_copy(update={"identity": "zhongshu-fixture"})})
        with self.assertRaises(GovernanceError):
            self.runtime.submit(req, changed)

    def test_interrupt_never_reaches_execution_department_directly(self):
        self.seed("EXECUTION", "WAR")
        ctx = self.context("EMPEROR")
        req = self.request(ctx, "IMPERIAL_INTERRUPT", "BLOCKED", "PRINCE", "INTAKE", "INTERRUPT", "INTERRUPT_RESULT", "CHANGE_REQUEST")
        self.runtime.submit(req, ctx)
        self.assertEqual(self.runtime.load()["tasks"][0]["next_role"], "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "CLASSIFY_INTERRUPT", "CHANGES_REQUESTED", "ZHONGSHU", "PLAN", "INTERRUPT", "INTERRUPT_RESULT", "CHANGE_REQUEST")
        req["interrupt"] = {"classification": "CHANGE_REQUEST", "impact": "scientific-method"}
        self.runtime.submit(req, ctx)
        task = self.runtime.load()["tasks"][0]
        self.assertEqual(task["imperial_authorization"]["status"], "NOT_REQUESTED")
        self.assertIsNone(task["review_result"])

    def test_governance_maintenance_preserves_scientific_state(self):
        self.seed("EXECUTION", "WAR")
        initial = deepcopy(self.runtime.load()["tasks"][0])
        ctx = self.context("PERSONNEL", maintenance=True)
        req = self.request(ctx, "GOVERNANCE_PATCH_COMPLETE", "EXECUTION", "WAR", "EXECUTE", "GOVERNANCE", "GOVERNANCE_RESULT", "COMPLETE")
        self.runtime.submit(req, ctx)
        self.assertEqual(self.runtime.load()["tasks"][0], initial)

    def test_trace_or_registry_corruption_fails_closed(self):
        self.seed()
        self.runtime.registry_path.write_bytes(self.runtime.registry_path.read_bytes() + b"\n# outside edit\n")
        self.denied("STATE_CONFLICT", self.runtime.load)

    def test_missing_trace_fails_closed(self):
        self.seed()
        (self.root / "governance/traces/000001.json").unlink()
        self.denied("STATE_CONFLICT", self.runtime.load)

    def test_crash_journal_replays_without_duplicate_evidence(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        real = self.runtime._finish
        with patch.object(self.runtime, "_finish", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.runtime.submit(req, ctx)
        self.denied("STATE_CONFLICT", self.runtime.load)
        self.runtime.recover()
        task_file = self.root / "governance/tasks/TEST-T01.md"
        self.assertEqual(task_file.read_text(encoding="utf-8").count("## ImperialFlow V1 Runtime Commit"), 1)
        self.assertEqual(self.runtime.load()["tasks"][0]["runtime"]["state"], "PLAN")

    def test_finished_task_is_immutable_to_scientific_actions(self):
        self.seed("DONE", None)
        ctx = Invocation.model_validate({"id": "after-done", "actor": {"role": "EMPEROR", "identity": "emperor-fixture"}})
        self.denied("TASK_ALREADY_DONE", lambda: self.runtime.begin("TEST-T01", ctx))

    def test_schema_rejects_untyped_boolean_evidence(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        req["evidence"] = {"task_start_authorized": True}
        self.denied("SCHEMA_VALIDATION_FAILED", lambda: self.runtime.submit(req, ctx))

    def test_full_high_risk_lifecycle_requires_separate_human_acceptance(self):
        self.seed(authorized=False)

        def step(role, action, state, next_role, phase, kind, result_type, value, **fields):
            ctx = self.context(role)
            req = self.request(ctx, action, state, next_role, phase, kind, result_type, value, **fields)
            event = self.runtime.submit(req, ctx)
            return self.runtime.load()["tasks"][0], req["artifacts"][0]["id"]

        step("EMPEROR", "START_TASK", "AUTHORIZED", "PRINCE", "INTAKE", "START_AUTHORIZATION", "TASK_START", "GRANTED", content="ACTION: START_TASK\nTASK_ID: TEST-T01\n")
        step("PRINCE", "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        task, plan = step("ZHONGSHU", "REQUEST_MENXIA_REVIEW", "REVIEW", "MENXIA", "REVIEW", "PLAN", "PLAN_RESULT", "COMPLETE")
        step("MENXIA", "APPROVE_PLAN", "EXECUTION_PREP", "SHANGSHU", "EXECUTION_PREP", "REVIEW", "REVIEW_RESULT", "APPROVE", plan_ref=plan)
        task, package = step("SHANGSHU", "REQUEST_IMPERIAL_AUTHORIZATION", "AWAITING_IMPERIAL_AUTHORIZATION", "EMPEROR", "AWAITING_IMPERIAL_AUTHORIZATION", "EXECUTION_PACKAGE", "PACKAGE_RESULT", "COMPLETE", plan_ref=plan, execution_roles=["WAR", "RITES"], scope_paths=["src/test.py", "docs/test.md"])
        self.assertEqual(task["imperial_authorization"]["status"], "PENDING")
        step("EMPEROR", "APPROVE_EXECUTION", "EXECUTION", "WAR", "EXECUTE", "EXECUTION_AUTHORIZATION", "IMPERIAL_DECISION", "APPROVE", plan_ref=plan, package_ref=package)
        step("WAR", "FORWARD_TO_NEXT_EXECUTOR", "EXECUTION", "RITES", "EXECUTE", "DELIVERABLE", "EXECUTION_RESULT", "COMPLETE")
        task, _ = step("RITES", "REQUEST_JUSTICE_VALIDATION", "VALIDATION", "JUSTICE", "VALIDATE", "DELIVERABLE", "EXECUTION_RESULT", "COMPLETE")
        self.assertEqual(task["execution_status"], "COMPLETE")
        task, validation = step("JUSTICE", "REQUEST_IMPERIAL_ACCEPTANCE", "AWAITING_IMPERIAL_ACCEPTANCE", "EMPEROR", "AWAITING_IMPERIAL_ACCEPTANCE", "VALIDATION", "VALIDATION_RESULT", "VALIDATION_PASS", plan_ref=plan)
        self.assertNotEqual(task["status"], "DONE")
        task, _ = step("EMPEROR", "ACCEPT_DELIVERY", "DONE", None, None, "ACCEPTANCE", "IMPERIAL_DECISION", "ACCEPTED", plan_ref=plan, validation_ref=validation)
        self.assertEqual(task["status"], "DONE")
        self.assertEqual(self.runtime.load()["last_completed_task"], "TEST-T01")

    def test_validation_evidence_for_stale_plan_is_rejected(self):
        self.seed("VALIDATION", "JUSTICE")
        ctx = self.context("JUSTICE")
        req = self.request(ctx, "REQUEST_IMPERIAL_ACCEPTANCE", "AWAITING_IMPERIAL_ACCEPTANCE", "EMPEROR", "AWAITING_IMPERIAL_ACCEPTANCE", "VALIDATION", "VALIDATION_RESULT", "VALIDATION_PASS", plan_ref="old-plan")
        self.denied("EVIDENCE_MISSING", lambda: self.runtime.submit(req, ctx))

    def test_reviewer_same_identity_as_author_is_rejected(self):
        self.seed("REVIEW", "MENXIA")
        original_context = Invocation.model_validate({"id": "self-review", "actor": {"role": "MENXIA", "identity": "zhongshu-fixture"}})
        self.runtime.begin("TEST-T01", original_context)
        req = self.request(original_context, "APPROVE_PLAN", "EXECUTION_PREP", "SHANGSHU", "EXECUTION_PREP", "REVIEW", "REVIEW_RESULT", "APPROVE", plan_ref="plan")
        req["artifacts"][0]["actor"]["identity"] = "zhongshu-fixture"
        self.denied("REVIEWER_INDEPENDENCE_VIOLATION", lambda: self.runtime.submit(req, original_context))

    def test_package_approval_for_different_package_is_denied(self):
        self.seed("AWAITING_IMPERIAL_AUTHORIZATION", "EMPEROR")
        ctx = self.context("EMPEROR")
        req = self.request(ctx, "APPROVE_EXECUTION", "EXECUTION", "WAR", "EXECUTE", "EXECUTION_AUTHORIZATION", "IMPERIAL_DECISION", "APPROVE", plan_ref="plan", package_ref="old-package")
        self.denied("EVIDENCE_MISSING", lambda: self.runtime.submit(req, ctx))

    def test_role_cannot_write_outside_workspace_via_evidence(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE")
        req["artifacts"][0]["path"] = "../escape.md"
        self.denied("ROLE_CAPABILITY_VIOLATION", lambda: self.runtime.submit(req, ctx))

    def test_review_budget_prevents_extra_rounds(self):
        self.seed("REVIEW", "MENXIA", counters={"review_rounds": 2})
        ctx = self.context("MENXIA")
        req = self.request(ctx, "APPROVE_PLAN", "EXECUTION_PREP", "SHANGSHU", "EXECUTION_PREP", "REVIEW", "REVIEW_RESULT", "APPROVE", plan_ref="plan")
        self.denied("BUDGET_EXCEEDED", lambda: self.runtime.submit(req, ctx))

    def test_interrupt_note_resumes_without_scope_change(self):
        self.seed("EXECUTION", "WAR")
        original = deepcopy(self.runtime.load()["tasks"][0])
        ctx = self.context("EMPEROR")
        req = self.request(ctx, "IMPERIAL_INTERRUPT", "BLOCKED", "PRINCE", "INTAKE", "INTERRUPT", "INTERRUPT_RESULT", "CHANGE_REQUEST")
        self.runtime.submit(req, ctx)
        ctx = self.context("PRINCE")
        req = self.request(ctx, "CLASSIFY_INTERRUPT", "EXECUTION", "WAR", "EXECUTE", "INTERRUPT", "INTERRUPT_RESULT", "NOTE")
        req["interrupt"] = {"classification": "NOTE", "impact": "none"}
        self.runtime.submit(req, ctx)
        task = self.runtime.load()["tasks"][0]
        for name in ("phase", "status", "review_result", "imperial_authorization", "execution_status"):
            self.assertEqual(task[name], original[name])

    def test_checkpoint_acceptance_does_not_complete_scientific_task(self):
        self.seed("PLAN", "YUSHITAI", task_type="GOVERNANCE_CHECKPOINT")
        ctx = self.context("YUSHITAI")
        req = self.request(ctx, "REQUEST_IMPERIAL_CHECKPOINT_DECISION", "PLAN", "EMPEROR", "AWAITING_IMPERIAL_CHECKPOINT_DECISION", "CHECKPOINT", "CHECKPOINT_AUDIT", "AUDIT_PASS")
        self.runtime.submit(req, ctx)
        ctx = self.context("EMPEROR")
        req = self.request(ctx, "ACCEPT_CHECKPOINT", "PLAN", None, None, "CHECKPOINT", "IMPERIAL_DECISION", "ACCEPTED")
        self.runtime.submit(req, ctx)
        task = self.runtime.load()["tasks"][0]
        self.assertEqual(task["checkpoint_acceptance"], "ACCEPTED")
        self.assertNotEqual(task["status"], "DONE")

    def test_void_content_cannot_be_relabelled_valid(self):
        self.seed("INTAKE", "PRINCE")
        ctx = self.context("PRINCE")
        content = "<!-- BEGIN VOID UNAUTHORIZED ORIGINAL RECORD -->\n# bad\nnot approval\n# end\n<!-- END VOID UNAUTHORIZED ORIGINAL RECORD -->\n"
        req = self.request(ctx, "FORWARD_TO_ZHONGSHU", "PLAN", "ZHONGSHU", "PLAN", "INTAKE", "INTAKE_RESULT", "COMPLETE", content=content, start="# bad", end="# end")
        artifact = req["artifacts"][0]
        artifact["sha256"] = digest(b"# bad\nnot approval\n")
        self.denied("VOID_ARTIFACT_REFERENCE", lambda: self.runtime.submit(req, ctx))


if __name__ == "__main__":
    unittest.main()
