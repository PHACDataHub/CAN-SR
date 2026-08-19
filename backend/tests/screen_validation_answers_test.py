from __future__ import annotations

from api.screen.router import _copy_ai_answers_to_human


class _Db:
    def __init__(self):
        self.calls = []

    def update_jsonb_column(self, citation_id, column, value, table_name):
        self.calls.append((citation_id, column, value, table_name))
        return True


def test_copy_ai_answers_only_fills_missing_stage_human_answers(monkeypatch):
    db = _Db()
    monkeypatch.setattr('api.screen.router.cits_dp_service', db)
    count = _copy_ai_answers_to_human(
        {
            'criteria': {
                'l1': [
                    {'question': 'Include study?'}, {'question': 'Has PDF?'},
                ],
            },
        },
        {
            'llm_l1_include_study': {'selected': 'Yes'},
            'human_l1_has_pdf': {'selected': 'No'},
            'llm_l1_has_pdf': {'selected': 'Yes'},
        }, 'l1', 7, 'citations',
    )
    assert count == 1
    assert db.calls[0][1] == 'human_l1_include_study'
    assert db.calls[0][2]['selected'] == 'Yes'
    assert db.calls[0][2]['source'] == 'validated_ai_answer'


def test_copy_ai_answers_supports_l2_and_json_strings(monkeypatch):
    db = _Db()
    monkeypatch.setattr('api.screen.router.cits_dp_service', db)
    count = _copy_ai_answers_to_human(
        {
            'criteria_parsed': {
                'l2': {'items': [{'question': 'Full text eligible?'}]},
            },
        },
        {'llm_l2_full_text_eligible': '{"selected": "Include"}'},
        'l2', 8, 'citations',
    )
    assert count == 1
    assert db.calls[0][1] == 'human_l2_full_text_eligible'
