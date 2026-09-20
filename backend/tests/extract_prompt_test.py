from __future__ import annotations

from api.extract.prompts import PARAMETER_PROMPT_JSON


def test_parameter_prompt_requires_evidence_for_negative_results():
    assert 'Use this for both positive and negative conclusions.' in PARAMETER_PROMPT_JSON
    assert 'list the sentence indices that support that conclusion' in PARAMETER_PROMPT_JSON
    assert 'Do not return an empty evidence_sentences array when relevant sentences support the explanation.' in PARAMETER_PROMPT_JSON


# Regression: the bulk run-all executor formatted this template without
# unit_instructions/calculation/options, so every citation in an extract run
# died on KeyError and was counted as failed.
def test_bulk_executor_supplies_every_placeholder_the_template_requires():
    from api.jobs.pipelines.screening_executor import _format_parameter_options

    item = {
        'name': 'Attack rate',
        'unit_instructions': 'Report as a percentage.',
        'calculation': 'cases / population',
        'options': [
            {'label': 'Reported', 'context': 'stated explicitly'},
            {'label': 'Not reported', 'context': None},
        ],
    }
    prompt = PARAMETER_PROMPT_JSON.format(
        parameter_name='Attack rate',
        parameter_description='desc',
        unit_instructions=str(item.get('unit_instructions') or ''),
        calculation=str(item.get('calculation') or ''),
        options=_format_parameter_options(item),
        fulltext='1. A sentence.',
        tables='(none)',
        figures='(none)',
    )
    assert 'Report as a percentage.' in prompt
    assert 'cases / population' in prompt
    assert '- Reported: stated explicitly' in prompt
    assert '- Not reported: ' in prompt


def test_free_text_parameter_renders_an_empty_option_block():
    from api.jobs.pipelines.screening_executor import _format_parameter_options

    assert _format_parameter_options({'name': 'Sample size'}) == ''
    assert _format_parameter_options(
        {'options': ['not-a-dict', {'label': ''}]},
    ) == ''
