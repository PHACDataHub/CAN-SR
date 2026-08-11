from __future__ import annotations

from api.extract.prompts import PARAMETER_PROMPT_JSON


def test_parameter_prompt_requires_evidence_for_negative_results():
    assert 'Use this for both positive and negative conclusions.' in PARAMETER_PROMPT_JSON
    assert 'list the sentence indices that support that conclusion' in PARAMETER_PROMPT_JSON
    assert 'Do not return an empty evidence_sentences array when relevant sentences support the explanation.' in PARAMETER_PROMPT_JSON
