from __future__ import annotations

from api.services.cit_db_service import snake_case_param
from api.services.screening_columns import column_index
from api.services.screening_columns import MAX_IDENTIFIER_BYTES
from api.services.screening_columns import parameter_columns
from api.services.screening_columns import resolve_existing
from api.services.screening_columns import screening_columns
from api.services.screening_columns import truncate_identifier

LONG_QUESTION = (
    'Is this article reporting on measles disease outcomes in a defined '
    'human population cohort with laboratory confirmation?'
)


def test_writers_current_names_are_stage_qualified():
    columns = screening_columns('l1', 'Is this primary research?')
    assert columns.human == 'human_l1_is_this_primary_research'
    assert columns.llm == 'llm_l1_is_this_primary_research'
    assert screening_columns('l2', 'Is this primary research?').llm == (
        'llm_l2_is_this_primary_research'
    )


def test_legacy_names_are_offered_as_a_fallback_after_the_current_one():
    columns = screening_columns('l1', 'Is this primary research?')
    assert columns.human_candidates == (
        'human_l1_is_this_primary_research', 'human_is_this_primary_research',
    )
    assert columns.llm_candidates == (
        'llm_l1_is_this_primary_research', 'llm_is_this_primary_research',
    )


def test_names_are_truncated_the_way_postgres_truncates_them():
    columns = screening_columns('l1', LONG_QUESTION)
    for name in (columns.human, columns.llm, columns.legacy_human, columns.legacy_llm):
        assert len(name.encode('utf-8')) <= MAX_IDENTIFIER_BYTES
    # Without truncation this name would be 65 characters and would never
    # match the column Postgres actually created.
    assert columns.human.startswith(
        'human_l1_is_this_article_reporting_on_measles',
    )


def test_truncation_does_not_split_a_multibyte_character():
    name = 'human_l1_' + ('é' * 40)
    truncated = truncate_identifier(name)
    assert len(truncated.encode('utf-8')) <= MAX_IDENTIFIER_BYTES
    truncated.encode('utf-8').decode('utf-8')


def test_parameter_key_matches_what_writers_store():
    name = (
        'Attack rate among unvaccinated household contacts during the '
        'outbreak period reported'
    )
    assert parameter_columns(name).llm == snake_case_param(name)
    assert parameter_columns(name).human == snake_case_param(name).replace(
        'llm_param_', 'human_param_', 1,
    )


def test_resolve_existing_prefers_earlier_candidates_and_keeps_real_casing():
    existing = column_index([
        {'column_name': 'LLM_L1_Question'}, {'column_name': 'llm_question'},
    ])
    assert resolve_existing(existing, ('llm_l1_question', 'llm_question')) == (
        'LLM_L1_Question'
    )
    assert resolve_existing(existing, ('llm_missing', 'llm_question')) == (
        'llm_question'
    )
    assert resolve_existing(existing, ('llm_absent',)) is None
