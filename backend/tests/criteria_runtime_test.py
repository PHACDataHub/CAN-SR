from __future__ import annotations

from api.criteria.runtime import item_is_visible


def test_trigger_prefers_stage_specific_human_answer() -> None:
    criteria = {
        'l1': [
            {
                'id': 'q1',
                'question': 'Primary research?',
                'options': [{'id': 'yes', 'label': 'Yes'}],
            },
            {
                'id': 'q2',
                'question': 'Human population?',
                'options': [{'id': 'yes', 'label': 'Yes'}],
                'trigger': {'all': [{'source_item_id': 'q1', 'option_id': 'yes'}]},
            },
        ],
    }

    assert item_is_visible(
        criteria, criteria['l1'][1], {
            'human_l1_primary_research': {'selected': 'Yes'},
        },
    )
    assert not item_is_visible(
        criteria, criteria['l1'][1], {
            'human_l1_primary_research': {'selected': 'No'},
            'llm_l1_primary_research': {'selected': 'Yes'},
        },
    )


def test_trigger_falls_back_to_llm_answer_when_human_answer_is_missing() -> None:
    criteria = {
        'l2': [
            {
                'id': 'q1',
                'question': 'Full text eligible?',
                'options': [{'id': 'yes', 'label': 'Yes'}],
            },
            {
                'id': 'q2',
                'question': 'Extract data?',
                'options': [{'id': 'yes', 'label': 'Yes'}],
                'trigger': {'all': [{'source_item_id': 'q1', 'option_id': 'yes'}]},
            },
        ],
    }

    assert item_is_visible(
        criteria, criteria['l2'][1], {
            'llm_l2_full_text_eligible': {'selected': 'Yes'},
        },
    )
    assert item_is_visible(
        criteria, criteria['l2'][1], {
            'llm_full_text_eligible': {'selected': 'Yes'},
        },
    )
    assert item_is_visible(
        criteria, criteria['l2'][1], {
            'human_l2_full_text_eligible': {'selected': 'Yes'},
        },
    )
