from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Role(StrEnum):
    EMPEROR = "EMPEROR"
    PRINCE = "PRINCE"
    ZHONGSHU = "ZHONGSHU"
    MENXIA = "MENXIA"
    SHANGSHU = "SHANGSHU"
    PERSONNEL = "PERSONNEL"
    REVENUE = "REVENUE"
    RITES = "RITES"
    WAR = "WAR"
    JUSTICE = "JUSTICE"
    WORKS = "WORKS"
    YUSHITAI = "YUSHITAI"


class Action(StrEnum):
    IMPERIAL_INTERRUPT = "IMPERIAL_INTERRUPT"
    CLASSIFY_INTERRUPT = "CLASSIFY_INTERRUPT"
    START_TASK = "START_TASK"
    APPROVE_EXECUTION = "APPROVE_EXECUTION"
    RETURN_TO_ZHONGSHU = "RETURN_TO_ZHONGSHU"
    HOLD = "HOLD"
    CANCEL = "CANCEL"
    ACCEPT_DELIVERY = "ACCEPT_DELIVERY"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    ACCEPT_CHECKPOINT = "ACCEPT_CHECKPOINT"
    FORWARD_TO_ZHONGSHU = "FORWARD_TO_ZHONGSHU"
    FORWARD_TO_EXECUTOR = "FORWARD_TO_EXECUTOR"
    HOLD_FOR_STATE_RECONCILIATION = "HOLD_FOR_STATE_RECONCILIATION"
    REPORT_STATE_CONFLICT = "REPORT_STATE_CONFLICT"
    REJECT_INVALID_REQUEST = "REJECT_INVALID_REQUEST"
    REQUEST_MENXIA_REVIEW = "REQUEST_MENXIA_REVIEW"
    REPORT_PLAN_BLOCKER = "REPORT_PLAN_BLOCKER"
    APPROVE_PLAN = "APPROVE_PLAN"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"
    REQUEST_IMPERIAL_AUTHORIZATION = "REQUEST_IMPERIAL_AUTHORIZATION"
    REPORT_EXECUTION_BLOCKER = "REPORT_EXECUTION_BLOCKER"
    REQUEST_ROUTE_CHANGE = "REQUEST_ROUTE_CHANGE"
    GOVERNANCE_PATCH_COMPLETE = "GOVERNANCE_PATCH_COMPLETE"
    STATE_RECONCILED = "STATE_RECONCILED"
    REPORT_GOVERNANCE_CONFLICT = "REPORT_GOVERNANCE_CONFLICT"
    FORWARD_TO_NEXT_EXECUTOR = "FORWARD_TO_NEXT_EXECUTOR"
    REQUEST_JUSTICE_VALIDATION = "REQUEST_JUSTICE_VALIDATION"
    REPORT_PLAN_DEFECT = "REPORT_PLAN_DEFECT"
    REQUEST_IMPERIAL_ACCEPTANCE = "REQUEST_IMPERIAL_ACCEPTANCE"
    RETURN_FOR_CORRECTION = "RETURN_FOR_CORRECTION"
    REQUEST_IMPERIAL_CHECKPOINT_DECISION = "REQUEST_IMPERIAL_CHECKPOINT_DECISION"
    RETURN_FOR_REMEDIATION = "RETURN_FOR_REMEDIATION"
    REPORT_CRITICAL_FINDING = "REPORT_CRITICAL_FINDING"


class TaskState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    AUTHORIZED = "AUTHORIZED"
    INTAKE = "INTAKE"
    PLAN = "PLAN"
    REVIEW = "REVIEW"
    EXECUTION_PREP = "EXECUTION_PREP"
    AWAITING_IMPERIAL_AUTHORIZATION = "AWAITING_IMPERIAL_AUTHORIZATION"
    EXECUTION = "EXECUTION"
    VALIDATION = "VALIDATION"
    AWAITING_IMPERIAL_ACCEPTANCE = "AWAITING_IMPERIAL_ACCEPTANCE"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CANCELLED = "CANCELLED"
    VOID = "VOID"


class Phase(StrEnum):
    INTAKE = "INTAKE"
    PLAN = "PLAN"
    REVIEW = "REVIEW"
    EXECUTION_PREP = "EXECUTION_PREP"
    AWAITING_IMPERIAL_AUTHORIZATION = "AWAITING_IMPERIAL_AUTHORIZATION"
    EXECUTE = "EXECUTE"
    VALIDATE = "VALIDATE"
    AWAITING_IMPERIAL_ACCEPTANCE = "AWAITING_IMPERIAL_ACCEPTANCE"
    CHECKPOINT_AUDIT = "CHECKPOINT_AUDIT"
    AWAITING_IMPERIAL_CHECKPOINT_DECISION = "AWAITING_IMPERIAL_CHECKPOINT_DECISION"


class ResultType(StrEnum):
    TASK_START = "TASK_START"
    INTAKE_RESULT = "INTAKE_RESULT"
    PLAN_RESULT = "PLAN_RESULT"
    REVIEW_RESULT = "REVIEW_RESULT"
    PACKAGE_RESULT = "PACKAGE_RESULT"
    EXECUTION_RESULT = "EXECUTION_RESULT"
    VALIDATION_RESULT = "VALIDATION_RESULT"
    IMPERIAL_DECISION = "IMPERIAL_DECISION"
    GOVERNANCE_RESULT = "GOVERNANCE_RESULT"
    INTERRUPT_RESULT = "INTERRUPT_RESULT"
    CHECKPOINT_AUDIT = "CHECKPOINT_AUDIT"
    BLOCKER = "BLOCKER"


class ResultValue(StrEnum):
    COMPLETE = "COMPLETE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    GRANTED = "GRANTED"
    PASS = "PASS"
    FAIL = "FAIL"
    VALIDATION_PASS = "VALIDATION_PASS"
    VALIDATION_FAIL = "VALIDATION_FAIL"
    AUDIT_PASS = "AUDIT_PASS"
    AUDIT_FINDINGS = "AUDIT_FINDINGS"
    ACCEPTED = "ACCEPTED"
    HOLD = "HOLD"
    CANCEL = "CANCEL"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    STATE_CONFLICT = "STATE_CONFLICT"
    BLOCKED = "BLOCKED"
    NOTE = "NOTE"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    NEW_TASK = "NEW_TASK"
    URGENT_FIX = "URGENT_FIX"


class EvidenceKind(StrEnum):
    START_AUTHORIZATION = "START_AUTHORIZATION"
    INTAKE = "INTAKE"
    PLAN = "PLAN"
    REVIEW = "REVIEW"
    EXECUTION_PACKAGE = "EXECUTION_PACKAGE"
    EXECUTION_AUTHORIZATION = "EXECUTION_AUTHORIZATION"
    DELIVERABLE = "DELIVERABLE"
    VALIDATION = "VALIDATION"
    ACCEPTANCE = "ACCEPTANCE"
    GOVERNANCE = "GOVERNANCE"
    CHECKPOINT = "CHECKPOINT"
    INTERRUPT = "INTERRUPT"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Actor(StrictModel):
    role: Role
    identity: str = Field(min_length=1)


class Invocation(StrictModel):
    """Caller context supplied by the trusted launcher, not by request prose."""
    id: str = Field(min_length=1)
    actor: Actor


class Result(StrictModel):
    type: ResultType
    value: ResultValue


class Routing(StrictModel):
    next_role: Role | None
    next_phase: Phase | None


class ActionObject(StrictModel):
    type: Action


class EvidenceArtifact(StrictModel):
    id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    kind: EvidenceKind
    status: Literal["VALID", "VOID"] = "VALID"
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: str | None = None
    end: str | None = None
    normalization: Literal["RAW", "LF", "PACKAGE"] = "RAW"
    actor: Actor
    plan_ref: str | None = None
    package_ref: str | None = None
    validation_ref: str | None = None
    scope_paths: list[str] = Field(default_factory=list)
    execution_roles: list[Role] = Field(default_factory=list)

    @model_validator(mode="after")
    def selectors_paired(self):
        if bool(self.start) != bool(self.end):
            raise ValueError("Both start and end selectors are required")
        return self


class Interrupt(StrictModel):
    classification: Literal["NOTE", "CHANGE_REQUEST", "NEW_TASK", "HOLD", "CANCEL", "URGENT_FIX"]
    impact: Literal["implementation-only", "interface", "scientific-method", "governance", "none"]
    resume_role: Role | None = None
    resume_phase: Phase | None = None


class TransitionRequest(StrictModel):
    protocol_version: Literal[1] = 1
    request_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0, strict=True)
    actor: Actor
    result: Result
    routing: Routing
    action: ActionObject
    target_state: TaskState
    evidence_refs: list[str] = Field(default_factory=list)
    artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    interrupt: Interrupt | None = None
    reconciliation_state: TaskState | None = None

    @model_validator(mode="after")
    def unique_refs(self):
        ids = [a.id for a in self.artifacts]
        if len(ids) != len(set(ids)) or len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Duplicate evidence identifiers")
        return self
