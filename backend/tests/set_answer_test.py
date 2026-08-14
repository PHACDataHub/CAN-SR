from __future__ import annotations

from api.citations.router import _set_answer_destinations
from api.citations.router import _set_answer_payload


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
