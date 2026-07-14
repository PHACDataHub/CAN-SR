from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from ...services.cit_db_service import cits_dp_service
from ...services.pdf_linkage_service import link_citation_pdf
from .base import JobContext
from .base import PipelineOutcome


class PdfLinkagePipeline:
    pipeline_key = 'pdf_linkage'

    async def compute_work_items(self, context: JobContext) -> list[int]:
        requested = context.config.get('citation_ids')
        eligible = await run_in_threadpool(
            cits_dp_service.list_pdf_linkage_ids, context.table_name,
        )
        if requested is None:
            return eligible
        requested_ids = {int(item) for item in requested}
        return [item for item in eligible if item in requested_ids]

    async def execute_item(
        self, context: JobContext, work_item: int,
    ) -> PipelineOutcome:
        result = await link_citation_pdf(
            citation_id=int(work_item),
            table_name=context.table_name,
            user_id=context.created_by,
        )
        kind = result.kind if result.kind in {'done', 'skipped', 'failed'} else 'failed'
        return PipelineOutcome(kind, reason=getattr(result, 'reason', None))

    def format_phase(self, work_item: int) -> str:
        return f'citation {work_item}'

    def error_stage(self, context: JobContext) -> str:
        return self.pipeline_key