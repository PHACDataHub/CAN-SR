from __future__ import annotations

import unittest
from unittest.mock import Mock
from unittest.mock import patch

from api.services.cit_db_service import CitsDPService


class DropTableTests(unittest.TestCase):
    def test_drop_table_commits_without_switching_autocommit(self) -> None:
        connection = Mock()
        cursor = connection.cursor.return_value
        service = CitsDPService()

        with patch('api.services.cit_db_service.postgres_server') as server:
            server.conn = connection
            service.drop_table('screening_table')

        cursor.execute.assert_called_once_with(
            'DROP TABLE IF EXISTS "screening_table" CASCADE',
        )
        connection.commit.assert_called_once_with()
        # Changing autocommit while a shared connection has an open transaction
        # raises ProgrammingError in psycopg. drop_table must use normal commit.
        self.assertNotIn('autocommit', connection.__dict__)

    def test_drop_table_rolls_back_on_failure(self) -> None:
        connection = Mock()
        connection.cursor.return_value.execute.side_effect = RuntimeError(
            'drop failed',
        )
        service = CitsDPService()

        with patch('api.services.cit_db_service.postgres_server') as server:
            server.conn = connection
            with self.assertRaisesRegex(RuntimeError, 'drop failed'):
                service.drop_table('screening_table', cascade=False)

        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()


class PdfLinkageEligibilityTests(unittest.TestCase):
    def test_only_lists_missing_pdfs_that_passed_l1(self) -> None:
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchall.return_value = [(3,), (8,)]
        service = CitsDPService()

        with (
            patch('api.services.cit_db_service.postgres_server') as server,
            patch.object(service, 'ensure_pdf_linkage_columns'),
            patch.object(service, 'create_column') as create_column,
        ):
            server.conn = connection
            result = service.list_pdf_linkage_ids('screening_table')

        self.assertEqual(result, [3, 8])
        create_column.assert_called_once_with(
            'human_l1_decision', 'TEXT', table_name='screening_table',
        )
        sql = ' '.join(cursor.execute.call_args.args[0].split())
        self.assertIn("COALESCE(fulltext_url, '') = ''", sql)
        self.assertIn("COALESCE(human_l1_decision, '') = 'include'", sql)
        self.assertTrue(sql.endswith('ORDER BY id'))


if __name__ == '__main__':
    unittest.main()
