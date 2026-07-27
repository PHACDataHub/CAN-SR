from __future__ import annotations

import pytest
from api.services.review_service import CompatibilityProjector
from api.services.review_service import extraction_answers_agree
from api.services.review_service import normalize_extraction_answer
from api.services.review_service import reviewer_identity
from api.services.review_service import WorkUnit


def test_work_unit_is_stable_and_parameter_requires_criterion():
    unit = WorkUnit(
        sr_id='sr-1', stage='extract', source_table_name='citations_1',
        citation_id=42, criteria_revision=3, criterion_key='pico',
        parameter_key='population',
    )
    assert unit.values() == (
        'sr-1', 'extract', 'citations_1', 42, 'pico', 'population', 3,
    )

    with pytest.raises(ValueError, match='requires criterion'):
        WorkUnit(
            sr_id='sr-1', stage='extract', source_table_name='citations_1',
            citation_id=42, criteria_revision=3, parameter_key='population',
        )


def test_work_unit_rejects_unsafe_dynamic_table_name():
    with pytest.raises(ValueError, match='safe SQL identifier'):
        WorkUnit(
            sr_id='sr-1', stage='l1', source_table_name='citations; DROP TABLE x',
            citation_id=1, criteria_revision=1,
        )


def test_reviewer_identity_comes_from_authenticated_user_and_normalizes_email():
    identity = reviewer_identity(
        {'id': 'user-7', 'email': ' Reviewer@Example.COM '},
    )
    assert identity.reviewer_id == 'user-7'
    assert identity.email == 'reviewer@example.com'
    assert reviewer_identity(
        {'email': 'Reviewer@Example.COM'},
    ).reviewer_id == 'reviewer@example.com'

    with pytest.raises(ValueError, match='stable reviewer identity'):
        reviewer_identity({})


def test_extraction_agreement_only_ignores_presentation_differences():
    assert normalize_extraction_answer('  A\nB  ') == 'a b'
    assert extraction_answers_agree('<p> A </p>', 'a')
    assert not extraction_answers_agree('10 mg', '10')
    assert not extraction_answers_agree(
        'heart attack', 'myocardial infarction',
    )


def test_legacy_projection_contains_only_validated_records():
    records = [
        {'reviewer_id': 'u1', 'state': 'draft', 'created_at': 'draft-time'},
        {'reviewer_id': 'u1', 'state': 'validated', 'validated_at': 't1'},
        {'reviewer_id': 'u2', 'state': 'validated', 'validated_at': 't2'},
    ]
    assert CompatibilityProjector.legacy_validation_list(records) == [
        {'user': 'u1', 'validated_at': 't1'},
        {'user': 'u2', 'validated_at': 't2'},
    ]


def test_projection_preserves_legacy_user_and_timestamp_shape():
    assert CompatibilityProjector.validation_entry(
        {'email': 'reviewer@example.com', 'created_at': 't0'},
    ) == {'user': 'reviewer@example.com', 'validated_at': 't0'}
