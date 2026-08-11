from __future__ import annotations

from api.screen.prompts import PROMPT_XML_TEMPLATE_FULLTEXT


def test_fulltext_screening_prompt_contains_all_evidence_context():
    prompt = PROMPT_XML_TEMPLATE_FULLTEXT.format(
        question='Does the study qualify?',
        options='Include\nExclude',
        xtra='Population guidance',
        fulltext='[0] Full text sentence',
        tables='Table [T1]\n| result |',
        figures='Figure [F2] caption: outcome',
    )

    assert '[0] Full text sentence' in prompt
    assert 'Table [T1]' in prompt
    assert 'Figure [F2]' in prompt
    assert '<evidence_sentences>' in prompt
    assert '<evidence_tables>' in prompt
    assert '<evidence_figures>' in prompt
