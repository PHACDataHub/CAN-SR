from __future__ import annotations

from api.jobs.pipelines.screening_executor import _should_skip_ai_output
from api.jobs.pipelines.screening_executor import _should_skip_human_answer


def test_existing_ai_answer_is_skipped_only_when_requested() -> None:
    assert not _should_skip_ai_output(
        'existing', force=False, skip_existing_ai=False,
    )
    assert _should_skip_ai_output(
        'existing', force=False, skip_existing_ai=True,
    )
    assert not _should_skip_ai_output(
        None, force=False, skip_existing_ai=True,
    )


def test_existing_human_answer_is_skipped_only_when_requested() -> None:
    assert not _should_skip_human_answer(
        'matched', force=False, skip_existing_human=False,
    )
    assert _should_skip_human_answer(
        'matched', force=False, skip_existing_human=True,
    )
    assert not _should_skip_human_answer(
        'blank', force=False, skip_existing_human=True,
    )


def test_force_preserves_rerun_everything_behavior() -> None:
    assert not _should_skip_ai_output(
        'existing', force=True, skip_existing_ai=True,
    )
    assert not _should_skip_human_answer(
        'matched', force=True, skip_existing_human=True,
    )
