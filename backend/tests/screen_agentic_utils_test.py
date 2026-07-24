from __future__ import annotations

import pytest
from api.screen.agentic_utils import AgentResponseError
from api.screen.agentic_utils import call_and_parse_agent_response
from api.screen.agentic_utils import parse_agent_xml
from api.screen.agentic_utils import validate_agent_response


def test_screening_requires_non_empty_rationale():
    parsed = parse_agent_xml(
        '<answer>Yes</answer><confidence>0.8</confidence><rationale> </rationale>',
    )

    assert parsed.parse_ok is True  # structural parser remains backward compatible
    assert parsed.missing_rationale is True
    assert validate_agent_response(parsed, stage='screening') == ['rationale']


def test_critical_does_not_require_rationale():
    parsed = parse_agent_xml(
        '<answer>None of the above</answer><confidence>0.75</confidence>',
    )

    assert validate_agent_response(parsed, stage='critical') == []


def test_invalid_confidence_is_reported_missing():
    parsed = parse_agent_xml(
        '<answer>Yes</answer><confidence>high</confidence><rationale>Grounded reason.</rationale>',
    )

    assert parsed.missing_confidence is True
    assert validate_agent_response(parsed, stage='screening') == ['confidence']


@pytest.mark.asyncio
async def test_screening_repairs_missing_rationale_once():
    responses = iter([
        ('<answer>Yes</answer><confidence>0.8</confidence>', 'first'),
        (
            '<answer>Yes</answer><confidence>0.8</confidence>'
            '<rationale>The abstract explicitly describes adult participants.</rationale>',
            'repair',
        ),
    ])
    prompts = []

    async def call_llm(prompt):
        prompts.append(prompt)
        return next(responses)

    raw, parsed, metadata, repaired = await call_and_parse_agent_response(
        'original prompt', stage='screening', call_llm=call_llm,
    )

    assert repaired is True
    assert metadata == 'repair'
    assert parsed.rationale.startswith('The abstract')
    assert raw.endswith('</rationale>')
    assert len(prompts) == 2
    assert 'Previous response:' in prompts[1]
    assert 'Original task and allowed options:' in prompts[1]
    assert 'original prompt' in prompts[1]


@pytest.mark.asyncio
async def test_screening_raises_after_failed_repair():
    async def call_llm(_prompt):
        return '<answer>Yes</answer><confidence>0.8</confidence>', None

    with pytest.raises(AgentResponseError, match='rationale') as exc_info:
        await call_and_parse_agent_response(
            'original prompt', stage='screening', call_llm=call_llm,
        )

    assert exc_info.value.missing_fields == ['rationale']
    assert exc_info.value.parsed is not None
    assert exc_info.value.parsed.answer == 'Yes'
    assert exc_info.value.parsed.confidence == 0.8
    assert exc_info.value.raw_response.startswith('<answer>Yes</answer>')
