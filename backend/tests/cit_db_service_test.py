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


class WorkspaceCitationTests(unittest.TestCase):
    def test_workspace_query_uses_metadata_allowlist_literal_search_and_stable_paging(self) -> None:
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchall.side_effect = [
            [
                {'column_name': 'id', 'data_type': 'integer'},
                {'column_name': 'title', 'data_type': 'text'},
                {'column_name': 'abstract', 'data_type': 'text'},
                {'column_name': 'llm_hidden', 'data_type': 'text'},
                {'column_name': 'payload', 'data_type': 'jsonb'},
            ],
            [{'id': 4, 'title': 'A 100% result', 'abstract': 'Text'}],
        ]
        cursor.fetchone.return_value = {'count': 1}
        service = CitsDPService()

        with patch('api.services.cit_db_service.postgres_server') as server:
            server.conn = connection
            result = service.list_workspace_citations(
                'screening_table', page=2, page_size=200, search='100%',
            )

        self.assertEqual(result['columns'], ['id', 'title', 'abstract'])
        self.assertEqual(result['page_size'], 100)
        self.assertEqual(result['citations'][0]['id'], 4)
        sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn('ILIKE %s ESCAPE', sql)
        self.assertNotIn('llm_hidden', sql)
        self.assertNotIn('payload', sql)
        self.assertIn('ORDER BY "id" ASC LIMIT %s OFFSET %s', sql)
        query_params = cursor.execute.call_args_list[-1].args[1]
        self.assertEqual(query_params[-2:], (100, 100))
        self.assertEqual(query_params[0], '%100\\%%')

    def test_workspace_query_discards_unknown_and_hidden_requested_columns(self) -> None:
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchall.side_effect = [
            [
                {'column_name': 'id', 'data_type': 'integer'},
                {'column_name': 'title', 'data_type': 'text'},
                {'column_name': 'llm_hidden', 'data_type': 'text'},
            ],
            [{'id': 4, 'title': 'A study'}],
        ]
        cursor.fetchone.side_effect = [{'count': 1}, (1, 4, 1)]
        service = CitsDPService()

        with patch('api.services.cit_db_service.postgres_server') as server:
            server.conn = connection
            result = service.list_workspace_citations(
                'screening_table', columns=['title', 'llm_hidden', 'unknown'],
            )

        self.assertEqual(result['columns'], ['id', 'title'])
        self.assertEqual(result['available_columns'], ['id', 'title'])
        sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn('SELECT "id", "title" FROM "screening_table"', sql)
        self.assertNotIn('llm_hidden', sql)
        self.assertNotIn('unknown', sql)


if __name__ == '__main__':
    unittest.main()
