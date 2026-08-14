from __future__ import annotations

from api.services.citation_duplicate_review_service import suggest_survivor


def test_suggest_survivor_prefers_complete_metadata_and_identifier_quality():
    result = suggest_survivor([
        {'id': 9, 'title': 'Study', 'abstract': 'Abstract', 'doi': ''},
        {'id': 4, 'title': 'Study', 'abstract': 'Abstract', 'doi': '10.1000/test'},
    ])

    assert result['suggested_survivor_id'] == 4
    assert result['survivor_reason'] == 'strongest_identifier'


def test_suggest_survivor_uses_oldest_record_then_lowest_id():
    result = suggest_survivor([
        {'id': 9, 'title': 'Study', 'created_at': '2002'},
        {'id': 4, 'title': 'Study', 'created_at': '2001'},
    ])

    assert result['suggested_survivor_id'] == 4
