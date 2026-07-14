from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal
from typing import Protocol


OutcomeKind = Literal['done', 'skipped', 'failed']


@dataclass(frozen=True)
class PipelineOutcome:
    kind: OutcomeKind
    reason: str | None = None

    @property
    def counts(self) -> tuple[int, int, int]:
        if self.kind == 'done':
            return (1, 0, 0)
        if self.kind == 'skipped':
            return (0, 1, 0)
        return (0, 0, 1)


@dataclass(frozen=True)
class JobContext:
    job_id: str
    sr_id: str
    sr: dict[str, Any]
    table_name: str
    created_by: str
    model: str | None
    config: dict[str, Any]
    step: str


class PipelineDefinition(Protocol):
    pipeline_key: str

    async def compute_work_items(self, context: JobContext) -> list[int]: ...

    async def execute_item(
        self, context: JobContext, work_item: int,
    ) -> PipelineOutcome: ...

    def format_phase(self, work_item: int) -> str: ...

    def error_stage(self, context: JobContext) -> str: ...