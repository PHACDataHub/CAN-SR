from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock
from unittest.mock import patch

from api.services.citation_duplicate_run_service import CitationDuplicateRunService


def test_finish_serializes_datetime_values_in_duplicate_result():
    connection = Mock()
    cursor = connection.cursor.return_value
    service = CitationDuplicateRunService()
    completed_at = datetime(2026, 8, 14, 5, 47, 21, 847000)
    result = {
        'groups': [
            {'members': [{'id': 1, 'created_at': completed_at}]},
        ],
    }

    with patch('api.services.citation_duplicate_run_service.postgres_server') as server:
        server.conn = connection
        service.finish('run-id', result)

    stored_result = cursor.execute.call_args.args[1][1]
    assert stored_result == (
        '{"groups": [{"members": [{"id": 1, '
        '"created_at": "2026-08-14T05:47:21.847000"}]}]}'
    )
    connection.commit.assert_called_once_with()
