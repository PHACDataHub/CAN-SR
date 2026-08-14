"""Pure review-only citation duplicate detection helpers."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from .citation_duplicate_review_service import suggest_survivor

POSSIBLE_MATCH_THRESHOLD = 0.70
MAX_LOOKAHEAD = 6


def normalize(value: Any) -> str:
    """Normalize values for matching while preserving meaningful Unicode letters."""
    if value is None:
        return ''
    text = unicodedata.normalize('NFKC', str(value)).casefold()
    text = ''.join(
        character for character in text
        if not unicodedata.category(character).startswith('C')
    )
    text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
    return ' '.join(text.split())


def _scores(left: dict[str, Any], right: dict[str, Any], fields: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for field in fields:
        left_value = normalize(left.get(field))
        right_value = normalize(right.get(field))
        if left_value and right_value:
            result[field] = (
                1.0
                if left_value == right_value
                else SequenceMatcher(None, left_value, right_value).ratio()
            )
    return result


def calculate_duplicate_statuses(
    rows: list[dict[str, Any]],
    fields: list[str],
    threshold: float = POSSIBLE_MATCH_THRESHOLD,
) -> dict[str, Any]:
    """Calculate exact/possible matches and connected candidate groups.

    Empty fields are neutral evidence: they are ignored when one or both values
    are empty. A pair must have at least one populated field in common, and the
    configured field list is unbounded; only the row lookahead is capped at six
    rows.
    """
    fields = list(dict.fromkeys(field for field in fields if field))
    lookahead = min(2 * len(fields), MAX_LOOKAHEAD) if fields else 0
    statuses = ['no_match'] * len(rows)
    parent = list(range(len(rows)))
    edges: list[dict[str, Any]] = []

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for index, left in enumerate(rows):
        for other in range(index + 1, min(len(rows), index + lookahead + 1)):
            evidence = _scores(left, rows[other], fields)
            if not evidence:
                continue
            exact = all(score == 1.0 for score in evidence.values())
            score = 1.0 if exact else sum(evidence.values()) / len(evidence)
            if not exact and score < threshold:
                continue
            status = 'exact' if exact else 'possible'
            statuses[index] = 'exact' if status == 'exact' else (
                'exact' if statuses[index] == 'exact' else 'possible'
            )
            statuses[other] = 'exact' if status == 'exact' else (
                'exact' if statuses[other] == 'exact' else 'possible'
            )
            union(index, other)
            edges.append({
                'left_index': index,
                'right_index': other,
                'status': status,
                'score': round(score, 5),
                'evidence': evidence,
            })

    groups: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if statuses[index] == 'no_match':
            continue
        root = find(index)
        group = groups.setdefault(
            root, {
                'group_id': f'duplicate-group-{len(groups) + 1}',
                'citation_ids': [],
                'status': 'possible',
            },
        )
        citation_id = row.get('id', index)
        if citation_id not in group['citation_ids']:
            group['citation_ids'].append(citation_id)
        if statuses[index] == 'exact':
            group['status'] = 'exact'

    row_results = []
    for index, row in enumerate(rows):
        group = next(
            (
                value for value in groups.values()
                if row.get('id', index) in value['citation_ids']
            ),
            None,
        )
        row_results.append({
            'status': statuses[index],
            'group_id': group['group_id'] if group else None,
            'score': max(
                (
                    edge['score'] for edge in edges
                    if index in (edge['left_index'], edge['right_index'])
                ),
                default=None,
            ),
        })
    return {
        'rows': row_results,
        'groups': list(groups.values()),
        'edges': edges,
        'lookahead': lookahead,
        'threshold': threshold,
    }


def recompute_affected_duplicate_groups(
    previous: dict[str, Any],
    deleted_ids: set[int],
    fields: list[str],
) -> dict[str, Any]:
    """Recompute only groups that contained one of the deleted citations."""
    deleted_ids = {int(citation_id) for citation_id in deleted_ids}
    rows = {
        int(item['citation_id']): dict(item)
        for item in previous.get('rows', [])
        if item.get('citation_id') is not None
        and int(item['citation_id']) not in deleted_ids
    }
    retained_groups = []
    affected_groups = []
    affected_ids: set[int] = set()
    for group in previous.get('groups', []):
        citation_ids = {
            int(citation_id) for citation_id in group.get('citation_ids', [])
        }
        if citation_ids & deleted_ids:
            affected_groups.append(group)
            affected_ids.update(citation_ids)
        else:
            retained_groups.append(group)

    recalculated_groups = []
    for previous_group in affected_groups:
        members = [
            dict(member)
            for member in previous_group.get('members', [])
            if int(member.get('id')) not in deleted_ids
        ]
        recalculated = calculate_duplicate_statuses(members, fields)
        statuses_by_id = {
            int(member.get('id', index)): {
                **status,
                'citation_id': int(member.get('id', index)),
            }
            for index, (member, status) in enumerate(
                zip(members, recalculated['rows']),
            )
        }
        for citation_id in affected_ids - deleted_ids:
            rows[citation_id] = statuses_by_id.get(
                citation_id, {
                    'citation_id': citation_id,
                    'status': 'no_match',
                    'group_id': None,
                    'score': None,
                },
            )
        for group_index, group in enumerate(recalculated['groups']):
            group_id = previous_group['group_id']
            if group_index:
                group_id = f'{group_id}-{group_index + 1}'
            group = {
                **group,
                'group_id': group_id,
                'members': [
                    {
                        **member,
                        **statuses_by_id[int(member.get('id'))],
                        'duplicate_group_id': group_id,
                    }
                    for member in members
                    if int(member.get('id')) in group['citation_ids']
                ],
            }
            group.update(suggest_survivor(group['members']))
            for member in group['members']:
                rows[int(member['id'])]['group_id'] = group_id
            recalculated_groups.append(group)

    result_rows = list(rows.values())
    return {
        **previous,
        'rows': result_rows,
        'groups': retained_groups + recalculated_groups,
        'edges': [],
        'duplicate_counts': {
            status: sum(
                1 for row in result_rows if row.get(
                    'status',
                ) == status
            )
            for status in ('exact', 'possible', 'no_match')
        },
    }
