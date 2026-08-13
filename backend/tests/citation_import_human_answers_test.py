from __future__ import annotations

from api.citations.router import _configured_l1_answer_columns
from api.citations.router import _match_csv_column_to_criterion


def test_configured_l1_answer_column_maps_to_its_human_criterion() -> None:
    sr = {
        'criteria_parsed': {
            'l1': {
                'questions': ['Is this primary research?'],
                'items': [{
                    'question': 'Is this primary research?',
                    'answer_column': 'Reviewer decision',
                }],
            },
        },
    }

    assert _configured_l1_answer_columns(sr) == {
        'Reviewer decision': 'is_this_primary_research',
    }


def test_legacy_l1_question_header_mapping_remains_supported() -> None:
    assert _match_csv_column_to_criterion(
        'L1 - Is this primary research?',
        {'is_this_primary_research': 'Is this primary research?'},
    ) == 'is_this_primary_research'
