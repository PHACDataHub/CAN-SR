from __future__ import annotations

import asyncio

from .procrastinate_app import PROCRASTINATE_APP
from ..services.cit_db_service import cits_dp_service
from ..services.citation_deduplication_preferences_service import citation_deduplication_preferences_service
from ..services.citation_duplicate_run_service import citation_duplicate_run_service


def run_citation_deduplication_sync(
    *,
    sr_id: str,
    table_name: str,
    actor_id: str,
    fields: list[str],
    dataset_revision,
    run_id: str,
) -> None:
    try:
        threshold = citation_deduplication_preferences_service.get_threshold(
            sr_id, table_name, actor_id,
        )
        revision, result = cits_dp_service.load_duplicate_rows(table_name, fields, threshold)
        if tuple(revision) != tuple(dataset_revision):
            citation_duplicate_run_service.finish(
                run_id,
                None,
                'Duplicate calculation skipped because the citation dataset changed before the run completed.',
            )
            return
        citation_duplicate_run_service.finish(run_id, result, None)
    except Exception as exc:
        citation_duplicate_run_service.finish(
            run_id,
            None,
            f'Duplicate calculation failed: {exc}',
        )


@PROCRASTINATE_APP.task(queue='default')
async def run_citation_deduplication(
    *,
    sr_id: str,
    table_name: str,
    actor_id: str,
    fields: list[str],
    dataset_revision,
    run_id: str,
) -> None:
    await asyncio.to_thread(
        run_citation_deduplication_sync,
        sr_id=sr_id,
        table_name=table_name,
        actor_id=actor_id,
        fields=fields,
        dataset_revision=dataset_revision,
        run_id=run_id,
    )