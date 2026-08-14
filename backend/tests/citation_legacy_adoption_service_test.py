from __future__ import annotations

from unittest.mock import Mock

import pytest
from api.services.citation_legacy_adoption_service import CitationLegacyAdoptionService


def _service_with_rows(*rows):
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = rows
    return CitationLegacyAdoptionService(connection_provider=Mock(conn=connection)), connection, cursor


def test_dry_run_validates_scope_and_returns_count_without_writes():
    service, connection, cursor = _service_with_rows((1,), (1,), (7,))

    result = service.adopt(
        'sr-1', 'sr_1_citations',
        'owner@example.test', dry_run=True,
    )

    assert result['dry_run'] is True
    assert result['citation_count'] == 7
    assert result['memberships_created'] == 0
    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    assert cursor.execute.call_count == 3


def test_adoption_writes_only_metadata_and_is_deterministic():
    service, connection, cursor = _service_with_rows((1,), (1,), (2,))
    cursor.rowcount = 2

    result = service.adopt('sr-1', 'sr_1_citations', 'owner@example.test')

    assert result['batch_id'] == service.legacy_batch_id(
        'sr-1', 'sr_1_citations',
    )
    assert result['citation_count'] == 2
    assert result['memberships_created'] == 2
    connection.commit.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'INSERT INTO citation_import_batches' in sql
    assert 'INSERT INTO citation_import_batch_memberships' in sql
    assert 'FROM "sr_1_citations"' in sql
    assert 'INSERT INTO "sr_1_citations"' not in sql


def test_adoption_rejects_table_not_owned_by_review_and_rolls_back():
    service, connection, _ = _service_with_rows(None)

    with pytest.raises(ValueError, match='not configured'):
        service.adopt('sr-1', 'sr_1_citations', 'owner@example.test')

    connection.rollback.assert_called_once_with()


def test_adoption_rejects_unsafe_dynamic_identifier_before_database_access():
    service = CitationLegacyAdoptionService(connection_provider=Mock())

    with pytest.raises(ValueError, match='Invalid citation_table_name'):
        service.adopt(
            'sr-1', 'citations; DROP TABLE users',
            'owner@example.test',
        )
