from __future__ import annotations

from collections.abc import Awaitable
from collections.abc import Callable

from fastapi.concurrency import run_in_threadpool

from .base import JobContext
from .base import PipelineOutcome


ScreeningExecutor = Callable[..., Awaitable[tuple[int, int, int]]]


class ScreeningPipeline:
    """Adapter around the existing screening citation executors.

    The injected functions keep this migration additive while moving pipeline
    selection and eligibility out of generic chunk orchestration.
    """

    pipeline_key = 'screening'

    def __init__(
        self,
        *,
        eligible_ids: Callable[..., list[int]],
        l1_executor: ScreeningExecutor,
        l2_executor: ScreeningExecutor,
        extract_executor: ScreeningExecutor,
    ) -> None:
        self._eligible_ids = eligible_ids
        self._executors = {
            'l1': l1_executor,
            'l2': l2_executor,
            'extract': extract_executor,
        }

    async def compute_work_items(self, context: JobContext) -> list[int]:
        return await run_in_threadpool(
            self._eligible_ids,
            sr_id=context.sr_id,
            table_name=context.table_name,
            step=context.step,
        )

    async def execute_item(
        self, context: JobContext, work_item: int,
    ) -> PipelineOutcome:
        try:
            executor = self._executors[context.step]
        except KeyError as exc:
            raise ValueError(f"Unsupported screening step: '{context.step}'") from exc

        common = {
            'job_id': context.job_id,
            'sr': context.sr,
            'table_name': context.table_name,
            'citation_id': int(work_item),
            'model': context.model,
            'force': bool(context.config.get('force')),
        }
        if context.step in {'l2', 'extract'}:
            common['sr_id'] = context.sr_id
        done, skipped, failed = await executor(**common)
        if failed:
            return PipelineOutcome('failed')
        if done:
            return PipelineOutcome('done')
        if skipped:
            return PipelineOutcome('skipped')
        return PipelineOutcome('skipped', reason='no_counted_output')

    def format_phase(self, work_item: int) -> str:
        return f'citation {work_item}'

    def error_stage(self, context: JobContext) -> str:
        return context.step