"""Structured model outputs accepted by the consultation graph."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ResearchTask(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    tool: str
    query: str = Field(min_length=1, max_length=4000)
    depends_on: list[str] = Field(default_factory=list)


class Question(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    reason: str = Field(default='', max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=8)


class Scenario(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)


class Plan(StrictModel):
    objective: str
    period: str | None = None
    constraints: dict = Field(default_factory=dict)
    assumptions: dict = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    tasks: list[ResearchTask] = Field(default_factory=list, max_length=24)
    clarification: Question | None = None
    scenarios: list[Scenario] = Field(default_factory=list, max_length=3)
    # Slugs from the provided playbook catalog whose full procedure this question needs.
    playbooks: list[str] = Field(default_factory=list, max_length=2)

    @model_validator(mode='after')
    def acyclic(self):
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate task id')
        done = set()
        while len(done) < len(ids):
            ready = {task.id for task in self.tasks if task.id not in done and set(task.depends_on) <= done}
            if not ready:
                raise ValueError('cyclic or missing task dependency')
            done |= ready
        return self


class Proposal(StrictModel):
    action: Literal['create_task', 'calendar_update', 'goal_update']
    payload: dict
    rationale: str = ''


class Memory(StrictModel):
    kind: Literal['profile', 'preference', 'constraint', 'priority']
    content: str = Field(min_length=1)


class FinalAnswer(StrictModel):
    answer: str = Field(min_length=1)
    proposals: list[Proposal] = Field(default_factory=list)
    memories: list[Memory] = Field(default_factory=list)


class DataCommand(StrictModel):
    command_index: int | None = Field(default=None, ge=0, le=11)
    separate_position: bool = False
    operation: Literal['create', 'read', 'update', 'delete']
    resource: str = Field(min_length=1, max_length=80)
    selector: dict = Field(default_factory=dict)
    values: dict = Field(default_factory=dict)
    source_quote: str = Field(min_length=1, max_length=8000)


class DataCommandPlan(StrictModel):
    commands: list[DataCommand] = Field(default_factory=list, max_length=8)
    message: str = Field(default='', max_length=2000)


class Review(StrictModel):
    valid: bool = True
    issues: list[str] = Field(default_factory=list)
    retry_tasks: list[str] = Field(default_factory=list)
    needs_replan: bool = False


class HistorySummary(StrictModel):
    content: str = Field(min_length=1, max_length=12000)
