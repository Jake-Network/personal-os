"""Public durable consultation workspace contract."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schema.advisor_schema import AskRequest

RunStatus = Literal["queued","running","waiting_input","blocked","cancel_requested","cancelled","completed","failed"]

class RunCreate(AskRequest):
    request_id: str = Field(min_length=1, max_length=128)
    depth: Literal["auto","deep"] = "auto"
    parent_revision: int | None = Field(default=None, ge=1)
    scenario_id: str | None = None

class Clarification(BaseModel):
    id: str
    question: str
    reason: str = ""
    options: list[str] = Field(default_factory=list)
    allow_unknown: bool = True

class ClarificationResponse(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    question_id: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=1)
    response: str = Field(min_length=1, max_length=8000)

class ArtifactRef(BaseModel):
    kind: str
    id: str
    revision: int = 1

class ScenarioCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    parent_id: str | None = None
    parent_revision: int | None = None
    assumptions: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)

class ScenarioView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: int
    run_id: str | None
    parent_id: str | None
    revision: int
    title: str
    assumptions: dict
    constraints: dict
    evidence: dict
    results: dict
    unknowns: list
    created_at: datetime

class ScenarioComparison(BaseModel):
    scenarios: list[ScenarioView] = Field(default_factory=list, max_length=3)
    evidence_basis: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

class ScenarioSelect(BaseModel):
    scenario_id: str | None
    expected_revision: int = Field(ge=1)

class ActionProposalView(BaseModel):
    id: int
    action: str
    payload: dict
    rationale: str | None = None

class MemoryProposalView(BaseModel):
    id: int
    kind: str
    content: str

class PlaybookUseView(BaseModel):
    revision_id: int
    playbook_id: int
    slug: str | None = None
    title: str
    revision: int

class RunResult(BaseModel):
    answer: str = ''
    message_id: int | None = None
    context_snapshot_id: str | None = None
    context: dict = Field(default_factory=dict)
    scenarios: list[str] = Field(default_factory=list)
    comparison: ScenarioComparison | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    proposals: list[ActionProposalView] = Field(default_factory=list)
    memory_proposals: list[MemoryProposalView] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    data_operations: list[dict] = Field(default_factory=list)
    playbooks: list[PlaybookUseView] = Field(default_factory=list)

class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    request_id: str
    conversation_id: int
    status: RunStatus
    revision: int
    depth: str
    result: RunResult | None
    clarification: Clarification | None
    error: str | None
    last_event_seq: int
    answer_revision: int
    created_at: datetime
    updated_at: datetime

class RunEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: str
    seq: int
    type: str
    revision: int
    payload: dict
    created_at: datetime

class WorkspaceView(BaseModel):
    conversation_id: int
    revision: int = 1
    problem: dict = Field(default_factory=dict)
    selected_scenario_id: str | None = None
    active_run: RunView | None = None
    latest_run: RunView | None = None
    scenarios: list[ScenarioView] = Field(default_factory=list)
    last_event_seq: int = 0
