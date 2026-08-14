from __future__ import annotations

import csv
from pathlib import Path

from api.services.citation_deduplication_service import calculate_duplicate_statuses
from api.services.citation_deduplication_service import normalize
from api.services.citation_deduplication_service import recompute_affected_duplicate_groups


def test_normalize_case_punctuation_and_unicode():
    assert normalize('  Café—Study! ') == 'café study'
    assert normalize(None) == ''


def test_empty_values_are_neutral_and_possible_matches_use_average_score():
    result = calculate_duplicate_statuses(
        [
            {'id': 1, 'title': 'Same', 'abstract': ''},
            {'id': 2, 'title': 'same', 'abstract': ''},
            {'id': 3, 'title': 'A study', 'abstract': 'An abstract'},
            {'id': 4, 'title': 'A stody', 'abstract': 'An abstrakt'},
        ], ['title', 'abstract'],
    )
    assert result['rows'][0]['status'] == 'exact'
    assert result['rows'][2]['status'] == 'possible'
    assert result['rows'][2]['score'] >= 0.7


def test_real_hcsf_sample_detects_duplicate_titles_with_empty_metadata():
    sample = Path(__file__).parents[3] / 'resources' / \
        'sample_files' / 'sr_HCSF - LLM Plenary Demo_citations.csv'
    with sample.open(newline='', encoding='utf-8-sig') as handle:
        source_rows = list(csv.DictReader(handle))

    rows = [
        {
            'id': index,
            'title': row.get('title'),
            'abstract': row.get('abstract'),
            'author': row.get('author'),
            'doi': row.get('doi'),
            'year': row.get('year'),
        }
        for index, row in enumerate(source_rows, 1)
    ]
    duplicate_title = 'social trends'
    duplicate_indexes = [
        index for index, row in enumerate(rows)
        if normalize(row['title']) == duplicate_title
    ]

    result = calculate_duplicate_statuses(
        rows, ['title', 'abstract', 'author', 'doi', 'year'],
    )

    assert len(duplicate_indexes) == 2
    assert all(
        result['rows'][index]['status'] in {'exact', 'possible'}
        for index in duplicate_indexes
    )
    assert any(
        set(group['citation_ids']) == {
            index + 1 for index in duplicate_indexes
        }
        for group in result['groups']
    )


def test_real_l1_sample_detects_repeated_titles():
    sample = Path(__file__).parents[3] / 'resources' / \
        'sample_files' / 'L1 Screening 2025_03_18 - fulltext - 100.csv'
    with sample.open(newline='', encoding='utf-8-sig') as handle:
        source_rows = list(csv.DictReader(handle))

    rows = [
        {
            'id': index,
            'title': row.get('Title'),
            'abstract': row.get('Abstract'),
            'author': row.get('Author'),
            'doi': row.get('DOI'),
            'year': row.get('Year'),
        }
        for index, row in enumerate(source_rows, 1)
    ]
    title_indexes = {}
    for index, row in enumerate(rows):
        title = normalize(row['title'])
        if title:
            title_indexes.setdefault(title, []).append(index)
    duplicate_indexes = next(
        indexes for indexes in title_indexes.values() if len(indexes) > 1
    )

    # Run the detector on the two real repeated-title records so the regression
    # focuses on matching semantics rather than the bounded row lookahead.
    candidate_rows = [rows[index] for index in duplicate_indexes]
    result = calculate_duplicate_statuses(candidate_rows, ['title'])

    assert all(
        item['status'] == 'exact' for item in result['rows']
    )


def test_field_count_is_unbounded_but_lookahead_is_capped():
    fields = [f'field_{index}' for index in range(10)]
    rows = [
        {'id': index, **{field: 'same' for field in fields}}
        for index in range(10)
    ]
    result = calculate_duplicate_statuses(rows, fields)
    assert result['lookahead'] == 6
    assert len(result['groups']) == 1
    assert len(result['groups'][0]['citation_ids']) == 10


def test_recompute_after_delete_preserves_unrelated_groups():
    previous = {
        'rows': [
            {
                'citation_id': 1, 'status': 'exact',
                'group_id': 'group-1', 'score': 1.0,
            },
            {
                'citation_id': 2, 'status': 'exact',
                'group_id': 'group-1', 'score': 1.0,
            },
            {
                'citation_id': 3, 'status': 'exact',
                'group_id': 'group-2', 'score': 1.0,
            },
            {
                'citation_id': 4, 'status': 'exact',
                'group_id': 'group-2', 'score': 1.0,
            },
        ],
        'groups': [
            {
                'group_id': 'group-1',
                'citation_ids': [1, 2],
                'status': 'exact',
                'members': [
                    {'id': 1, 'title': 'same'},
                    {'id': 2, 'title': 'same'},
                ],
            },
            {
                'group_id': 'group-2',
                'citation_ids': [3, 4],
                'status': 'exact',
                'members': [
                    {'id': 3, 'title': 'other'},
                    {'id': 4, 'title': 'other'},
                ],
            },
        ],
        'lookahead': 2,
    }

    result = recompute_affected_duplicate_groups(previous, {1}, ['title'])

    assert [group['group_id'] for group in result['groups']] == ['group-2']
    assert [row['citation_id'] for row in result['rows']] == [2, 3, 4]
    assert result['rows'][0]['status'] == 'no_match'
    assert result['groups'][0]['citation_ids'] == [3, 4]
