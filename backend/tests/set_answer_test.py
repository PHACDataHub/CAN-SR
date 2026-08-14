from __future__ import annotations

from api.citations.router import _set_answer_destinations
from api.citations.router import _set_answer_payload
from api.citations.router import _set_answer_upsert_validation
from api.citations.router import _set_answer_validation_columns


def test_l1_set_answer_writes_both_stage_columns() -> None:
    assert _set_answer_destinations('l1', 'primary_research') == [
        'human_l1_primary_research', 'human_l2_primary_research',
    ]


def test_l2_set_answer_writes_only_l2() -> None:
    assert _set_answer_destinations('l2', 'full_text_eligible') == [
        'human_l2_full_text_eligible',
    ]


def test_parameter_set_answer_writes_only_parameter_column() -> None:
    assert _set_answer_destinations('parameter', 'sample_size') == [
        'human_param_sample_size',
    ]


def test_set_answer_uses_step_specific_validation_columns() -> None:
    assert _set_answer_validation_columns('l1') == (
        'l1_validations', 'l1_validated_by', 'l1_validated_at',
    )
    assert _set_answer_validation_columns('l2') == (
        'l2_validations', 'l2_validated_by', 'l2_validated_at',
    )
    assert _set_answer_validation_columns('parameter') == (
        'parameters_validations', 'parameters_validated_by', 'parameters_validated_at',
    )


def test_set_answer_validation_upsert_preserves_other_reviewers() -> None:
    existing = [
        {'user': 'other@example.com', 'validated_at': '2026-01-01T00:00:00Z'},
        {'user': 'reviewer@example.com', 'validated_at': '2026-01-02T00:00:00Z'},
    ]
    assert _set_answer_upsert_validation(
        existing, 'reviewer@example.com', '2026-01-03T00:00:00Z',
    ) == [
        {'user': 'reviewer@example.com', 'validated_at': '2026-01-03T00:00:00Z'},
        {'user': 'other@example.com', 'validated_at': '2026-01-01T00:00:00Z'},
    ]


def test_set_answer_validation_upsert_accepts_legacy_shapes() -> None:
    assert _set_answer_upsert_validation(
        '[{"email": "other@example.com", "timestamp": "2026-01-01T00:00:00Z"}]',
        'reviewer@example.com',
        '2026-01-02T00:00:00Z',
    ) == [
        {'user': 'reviewer@example.com', 'validated_at': '2026-01-02T00:00:00Z'},
        {'user': 'other@example.com', 'validated_at': '2026-01-01T00:00:00Z'},
    ]


def test_set_answer_payload_preserves_source_value_and_provenance() -> None:
    answer = _set_answer_payload('  Yes  ', 'l1', 'l1')
    assert answer['selected'] == 'Yes'
    assert answer['human'] is True
    assert answer['source'] == 'retrospective_validation'
    assert answer['screening_step'] == 'l1'


def test_parameter_payload_uses_extraction_shape() -> None:
    answer = _set_answer_payload('42', 'parameter', 'parameter')
    assert answer['found'] is True
    assert answer['value'] == '42'
    assert answer['evidence_sentences'] == []
