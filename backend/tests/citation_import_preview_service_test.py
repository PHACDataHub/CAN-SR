from __future__ import annotations

import hashlib
import json
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from api.services.citation_import_preview_service import _normalized_external_id
from api.services.citation_import_preview_service import _row_external_ids
from api.services.citation_import_preview_service import build_preview
from api.services.citation_import_preview_service import CitationImportPreviewRepository
from api.services.citation_import_preview_service import CitationImportPreviewService
from api.services.citation_import_schema import COMMIT_SUPPORTED_FIELD_KEYS
from api.services.citation_import_schema import is_protected_citation_column
from api.services.citation_import_schema import safe_additional_field_name


class MemoryStorage:
    container_name = 'test-storage'

    def __init__(self):
        self.contents: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put_bytes_by_path(self, path: str, content: bytes, content_type: str = '') -> bool:
        self.contents[path] = content
        return True

    async def delete_by_path(self, path: str) -> bool:
        self.deleted.append(path)
        self.contents.pop(path, None)
        return True

    async def get_bytes_by_path(self, path: str) -> tuple[bytes, str]:
        return self.contents[path], path.rsplit('/', 1)[-1]


def test_csv_preview_normalizes_headers_and_reports_invalid_rows() -> None:
    preview = build_preview(
        'citations.csv',
        b'Title,Abstract,DOI\nFirst,An abstract,10.1/a\nSecond,,10.1/b\n',
    )

    assert preview['source_format'] == 'csv'
    assert preview['proposed_mapping'] == {
        'title': 'Title', 'abstract': 'Abstract',
    }
    assert preview['validation_report']['row_count'] == 2
    assert preview['validation_report']['missing_required_value_counts'] == {
        'title': 0, 'abstract': 1,
    }
    assert preview['validation_report']['valid_for_commit'] is False
    assert preview['schema_fingerprint'].startswith('sha256:')


def test_preview_reports_unmapped_required_columns() -> None:
    preview = build_preview('citations.csv', b'Name,Summary\nOne,Text\n')

    assert preview['validation_report']['missing_required_fields'] == [
        'title', 'abstract',
    ]
    assert preview['validation_report']['missing_required_value_counts'] == {
        'title': 1, 'abstract': 1,
    }


def test_preview_reports_columns_requiring_explicit_mapping_decision() -> None:
    preview = build_preview(
        'citations.csv', b'Title,Abstract,DOI\nOne,Text,10.1/a\n',
    )

    assert preview['validation_report']['unclassified_source_columns'] == [
        'DOI',
    ]


def test_reconciliation_uses_normalized_doi_before_fingerprint_and_reports_examples() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [('doi', '10.1000/example', 41)]
    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).reconcile(
        'sr-1', 'sr_1_citations', [
            {
                'Title': 'Changed title', 'Abstract': 'Changed abstract',
                'DOI': 'https://doi.org/10.1000/EXAMPLE.',
            },
            {'Title': 'New title', 'Abstract': 'New abstract'},
            {'Title': 'New title', 'Abstract': 'New abstract'},
            {'Title': 'Missing abstract', 'Abstract': ''},
        ], {'title': 'Title', 'abstract': 'Abstract'},
    )

    assert result['counts'] == {
        'new': 1, 'existing_exact_match': 2,
        'ambiguous': 0, 'excluded_ambiguous': 0, 'invalid': 1,
    }
    assert result['examples'][0] == {
        'row_number': 1, 'outcome': 'existing_exact_match', 'citation_id': 41,
    }
    assert result['examples'][2] == {
        'row_number': 3, 'outcome': 'existing_exact_match',
    }


def test_external_id_headers_and_values_are_normalized_with_namespaces() -> None:
    assert _normalized_external_id('pubmed', ' PMID: 00123 ') == '00123'
    assert _row_external_ids({
        'PubMed ID': 'PMID: 123', 'Embase ID': 'EMBASE: L123',
        'Scopus EID': 'EID: 2-s2.0-1', 'Web of Science ID': 'WOS: 0001',
    }) == [
        ('pubmed', '123'), ('embase', 'l123'), (
            'scopus',
            '2-s2.0-1',
        ), ('web_of_science', '0001'),
    ]


def test_reconciliation_external_ids_are_namespace_isolated_and_conflicts_are_ambiguous() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [
        ('external_id', 'pubmed', '123', 41), ('external_id', 'scopus', '123', 42),
    ]
    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).reconcile(
        'sr-1', 'sr_1_citations', [
            {'Title': 'A', 'Abstract': 'B', 'PubMed ID': '123'},
            {'Title': 'C', 'Abstract': 'D', 'Web of Science ID': '123'},
            {'Title': 'E', 'Abstract': 'F', 'PubMed ID': '123', 'Scopus EID': '123'},
        ], {'title': 'Title', 'abstract': 'Abstract'},
    )

    assert result['counts'] == {
        'new': 1, 'existing_exact_match': 1,
        'ambiguous': 1, 'excluded_ambiguous': 0, 'invalid': 0,
    }
    assert result['ambiguous_row_numbers'] == [3]


def test_reconciliation_detects_in_file_and_durable_cross_identity_conflicts() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [('external_id', 'pubmed', '123', 41)]
    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).reconcile(
        'sr-1', 'sr_1_citations', [
            {'Title': 'A', 'Abstract': 'B', 'Scopus EID': '2-s2.0-1'},
            {
                'Title': 'C', 'Abstract': 'D',
                'Scopus EID': '2-s2.0-1', 'PubMed ID': '123',
            },
        ], {'title': 'Title', 'abstract': 'Abstract'},
    )

    assert result['counts'] == {
        'new': 1, 'existing_exact_match': 0,
        'ambiguous': 1, 'excluded_ambiguous': 0, 'invalid': 0,
    }


def test_reconciliation_reports_ambiguous_durable_identity() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [
        ('doi', '10.1000/example', 41), ('doi', '10.1000/example', 42),
    ]
    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).reconcile(
        'sr-1', 'sr_1_citations', [{
            'Title': 'A',
            'Abstract': 'B', 'DOI': 'doi:10.1000/example',
        }],
        {'title': 'Title', 'abstract': 'Abstract'},
    )

    assert result['counts'] == {
        'new': 0, 'existing_exact_match': 0,
        'ambiguous': 1, 'excluded_ambiguous': 0, 'invalid': 0,
    }
    assert result['ambiguous_details'] == [{
        'row_number': 1,
        'matches': [{'identity_kind': 'doi', 'identifier_namespace': None, 'normalized_value': '10.1000/example', 'citation_ids': [41, 42]}],
    }]


def test_reconciliation_excludes_only_explicitly_resolved_ambiguous_rows() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [
        ('external_id', 'pubmed', '123', 41), ('external_id', 'scopus', '123', 42),
    ]
    repository = CitationImportPreviewRepository(
        connection_provider=Mock(conn=connection),
    )

    result = repository.reconcile(
        'sr-1', 'sr_1_citations',
        [{'Title': 'A', 'Abstract': 'B', 'PubMed ID': '123', 'Scopus EID': '123'}],
        {'title': 'Title', 'abstract': 'Abstract'}, [1],
    )

    assert result['counts'] == {
        'new': 0, 'existing_exact_match': 0,
        'ambiguous': 0, 'excluded_ambiguous': 1, 'invalid': 0,
    }
    assert result['ambiguous_row_numbers'] == [1]
    with pytest.raises(ValueError, match='Only currently ambiguous'):
        repository.reconcile(
            'sr-1', 'sr_1_citations',
            [{'Title': 'A', 'Abstract': 'B', 'PubMed ID': '123', 'Scopus EID': '123'}],
            {'title': 'Title', 'abstract': 'Abstract'}, [2],
        )


def test_import_schema_registry_limits_mapping_to_current_commit_capabilities() -> None:
    assert COMMIT_SUPPORTED_FIELD_KEYS == ('title', 'abstract')


def test_additional_field_policy_generates_safe_names_and_rejects_collisions() -> None:
    assert safe_additional_field_name(
        'Publication Date',
    ) == 'import_publication_date'
    assert safe_additional_field_name('2024 Notes') == 'import_2024_notes'
    assert is_protected_citation_column('id') is True
    assert is_protected_citation_column('llm_decision') is True
    with pytest.raises(ValueError, match='collides'):
        safe_additional_field_name('DOI', existing_columns=['import_doi'])


@pytest.mark.asyncio
async def test_service_revalidates_staging_and_refreshes_reconciliation_on_mapping_update() -> None:
    storage = MemoryStorage()
    repository = Mock()
    preview_id = '00000000-0000-0000-0000-000000000001'
    locator = 'test-storage/citation-import-previews/sr-1/preview.fernet'
    repository.get_active.return_value = {
        'citation_table_name': 'sr_1_citations',
        'validation_report': {'source_columns': ['Title', 'Abstract', 'Alt abstract']},
    }
    repository.get_staging_locator.return_value = locator
    repository.reconcile.return_value = {
        'counts': {
            'new': 1, 'existing_exact_match': 0, 'ambiguous': 0, 'invalid': 0,
        }, 'examples': [],
    }
    repository.update_mapping_decision.return_value = {
        'proposed_mapping': {'title': 'Title', 'abstract': 'Abstract'},
        'mapping_decision': {'version': 1, 'approved_mapping': {'title': 'Title', 'abstract': 'Abstract'}, 'excluded_source_columns': ['DOI']},
        'validation_report': {'row_count': 1, 'valid_for_commit': True},
    }
    service = CitationImportPreviewService(
        storage, repository, secret_key='unit-test-secret',
    )
    storage.contents[locator] = service._fernet.encrypt(
        json.dumps({
            'normalized_rows': [{'Title': 'A', 'Abstract': '', 'Alt abstract': 'B'}],
        }).encode(),
    )

    result = await service.update_mapping(
        preview_id=preview_id, sr_id='sr-1', actor_id='owner@example.test',
        approved_mapping={'title': 'Title', 'abstract': 'Alt abstract'}, excluded_source_columns=['Abstract'],
    )

    assert result['id'] == preview_id
    assert result['mapping_decision']['excluded_source_columns'] == ['DOI']
    refreshed_report = repository.update_mapping_decision.call_args.args[5]
    assert refreshed_report['missing_required_value_counts'] == {
        'title': 0, 'abstract': 0,
    }
    assert refreshed_report['reconciliation']['counts']['new'] == 1


def test_repository_mapping_update_locks_active_owned_preview_and_persists_decision() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = (
        {'title': 'Title', 'abstract': 'Abstract'},
        {
            'row_count': 1, 'source_columns': ['Title', 'Abstract', 'DOI'],
            'missing_required_value_counts': {'title': 0, 'abstract': 0}, 'valid_for_commit': True,
        },
    )
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).update_mapping_decision(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
        {'title': 'Title', 'abstract': 'Abstract'}, ['DOI'],
        {
            'row_count': 1, 'source_columns': ['Title', 'Abstract', 'DOI'],
            'missing_required_value_counts': {'title': 0, 'abstract': 0}, 'valid_for_commit': True,
            'reconciliation': {'counts': {'new': 1, 'existing_exact_match': 0, 'ambiguous': 0, 'invalid': 0}, 'examples': []},
        },
    )

    assert result['validation_report']['valid_for_commit'] is True
    assert result['mapping_decision']['version'] == 1
    connection.commit.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'FOR UPDATE' in sql
    assert 'created_by = %s' in sql
    assert 'mapping_decision = %s::jsonb' in sql


def test_repository_mapping_update_rejects_unclassified_source_columns() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = (
        {'title': 'Title', 'abstract': 'Abstract'},
        {'row_count': 1, 'source_columns': ['Title', 'Abstract', 'DOI']},
    )
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    with pytest.raises(ValueError, match='mapped or explicitly excluded'):
        CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).update_mapping_decision(
            '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
            {'title': 'Title', 'abstract': 'Abstract'}, [], {},
        )
    connection.rollback.assert_called_once_with()


@pytest.mark.asyncio
async def test_service_encrypts_staging_and_writes_only_preview_metadata() -> None:
    storage = MemoryStorage()
    repository = Mock()
    repository.reconcile.return_value = {
        'counts': {
            'new': 1, 'existing_exact_match': 0, 'ambiguous': 0, 'invalid': 0,
        }, 'examples': [],
    }
    service = CitationImportPreviewService(
        storage, repository, secret_key='unit-test-secret', ttl_minutes=30,
    )
    raw = b'Title,Abstract\nConfidential title,Confidential abstract\n'

    response = await service.create(
        sr_id='sr-1', citation_table_name='sr_1_citations', filename='citations.csv',
        raw_bytes=raw, commit_key='request-1', actor_id='owner@example.test',
    )

    assert response['validation_report']['valid_for_commit'] is True
    assert response['staging_expires_at'].endswith('+00:00')
    assert len(storage.contents) == 1
    ciphertext = next(iter(storage.contents.values()))
    assert raw not in ciphertext
    staged = json.loads(service._fernet.decrypt(ciphertext))
    assert staged['filename'] == 'citations.csv'
    assert staged['normalized_rows'] == [
        {'Title': 'Confidential title', 'Abstract': 'Confidential abstract'},
    ]
    record = repository.create.call_args.args[0]
    assert record['encrypted_staging_locator'] in storage.contents
    assert 'normalized_rows' not in record
    assert 'raw_file_base64' not in record


@pytest.mark.asyncio
async def test_service_removes_staged_ciphertext_when_metadata_write_fails() -> None:
    storage = MemoryStorage()
    repository = Mock()
    repository.create.side_effect = RuntimeError('database unavailable')
    service = CitationImportPreviewService(
        storage, repository, secret_key='unit-test-secret',
    )

    with pytest.raises(RuntimeError, match='database unavailable'):
        await service.create(
            sr_id='sr-1', citation_table_name=None, filename='citations.csv',
            raw_bytes=b'Title,Abstract\nA,B\n', commit_key='request-1', actor_id='owner@example.test',
        )

    assert len(storage.deleted) == 1
    assert storage.contents == {}


def test_repository_insert_targets_only_preview_metadata_table() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).create({
        'id': '00000000-0000-0000-0000-000000000001', 'sr_id': 'sr-1',
        'citation_table_name': 'sr_1_citations', 'source_sha256': 'hash', 'schema_fingerprint': 'schema',
        'proposed_mapping': {}, 'validation_report': {}, 'encrypted_staging_locator': 'store/path',
        'staging_expires_at': '2026-01-01T00:00:00+00:00', 'commit_key': 'key', 'created_by': 'owner',
    })

    sql = cursor.execute.call_args.args[0]
    assert 'INSERT INTO citation_import_previews' in sql
    assert 'citation_import_batches' not in sql
    assert 'sr_1_citations' not in sql
    assert json.loads(cursor.execute.call_args.args[1][5]) == {}


@pytest.mark.asyncio
async def test_cancel_marks_owned_preview_final_and_deletes_its_ciphertext() -> None:
    storage = MemoryStorage()
    repository = Mock()
    repository.cancel.return_value = 'test-storage/citation-import-previews/sr-1/preview.fernet'
    service = CitationImportPreviewService(
        storage, repository, secret_key='unit-test-secret',
    )

    result = await service.cancel(
        preview_id='00000000-0000-0000-0000-000000000001', sr_id='sr-1', actor_id='owner@example.test',
    )

    assert result == {
        'id': '00000000-0000-0000-0000-000000000001',
        'cancelled': True, 'staging_cleanup_pending': False,
    }
    repository.cancel.assert_called_once_with(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
    )
    assert storage.deleted == [
        'test-storage/citation-import-previews/sr-1/preview.fernet',
    ]


@pytest.mark.asyncio
async def test_cancel_rejects_preview_not_owned_or_already_finalized_without_deleting() -> None:
    storage = MemoryStorage()
    repository = Mock()
    repository.cancel.return_value = None
    service = CitationImportPreviewService(
        storage, repository, secret_key='unit-test-secret',
    )

    with pytest.raises(LookupError, match='not found'):
        await service.cancel(
            preview_id='00000000-0000-0000-0000-000000000001', sr_id='sr-1', actor_id='other@example.test',
        )

    assert storage.deleted == []


@pytest.mark.asyncio
async def test_cancel_reports_cleanup_pending_after_metadata_cancellation() -> None:
    storage = MemoryStorage()
    storage.delete_by_path = AsyncMock(
        side_effect=OSError('storage unavailable'),
    )
    repository = Mock()
    repository.cancel.return_value = 'test-storage/citation-import-previews/sr-1/preview.fernet'
    service = CitationImportPreviewService(
        storage, repository, secret_key='unit-test-secret',
    )

    result = await service.cancel(
        preview_id='00000000-0000-0000-0000-000000000001', sr_id='sr-1', actor_id='owner@example.test',
    )

    assert result['cancelled'] is True
    assert result['staging_cleanup_pending'] is True


def test_repository_cancel_scopes_owner_and_never_updates_citation_rows() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = ('test-storage/staged.fernet',)
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    locator = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).cancel(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
    )

    assert locator == 'test-storage/staged.fernet'
    sql = cursor.execute.call_args.args[0]
    assert 'UPDATE citation_import_previews' in sql
    assert 'created_by = %s' in sql
    assert 'committed_batch_id IS NULL' in sql
    assert 'staging_expires_at > CURRENT_TIMESTAMP' in sql
    assert 'citation_import_batches' not in sql
    assert 'INSERT INTO' not in sql


def test_inspect_returns_active_owned_metadata_without_staging_locator() -> None:
    repository = Mock()
    repository.get_active.return_value = {
        'id': '00000000-0000-0000-0000-000000000001', 'citation_table_name': 'sr_1_citations',
        'source_sha256': 'source-hash', 'schema_fingerprint': 'sha256:schema',
        'proposed_mapping': {'title': 'Title', 'abstract': 'Abstract'},
        'validation_report': {'row_count': 1, 'valid_for_commit': True},
        'staging_expires_at': '2026-01-01T01:00:00+00:00', 'created_at': '2026-01-01T00:00:00+00:00',
    }
    service = CitationImportPreviewService(
        MemoryStorage(), repository, secret_key='unit-test-secret',
    )

    result = service.inspect(
        preview_id='00000000-0000-0000-0000-000000000001', sr_id='sr-1', actor_id='owner@example.test',
    )

    assert result['validation_report']['valid_for_commit'] is True
    assert 'encrypted_staging_locator' not in result
    repository.get_active.assert_called_once_with(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
    )


def test_inspect_rejects_unavailable_preview() -> None:
    repository = Mock()
    repository.get_active.return_value = None
    service = CitationImportPreviewService(
        MemoryStorage(), repository, secret_key='unit-test-secret',
    )

    with pytest.raises(LookupError, match='not found'):
        service.inspect(
            preview_id='00000000-0000-0000-0000-000000000001', sr_id='sr-1', actor_id='other@example.test',
        )


def test_repository_inspect_scopes_active_owner_and_excludes_encrypted_staging() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = (
        '00000000-0000-0000-0000-000000000001', 'sr_1_citations', 'source-hash', 'sha256:schema',
        {'title': 'Title', 'abstract': 'Abstract'}, {'row_count': 1},
        datetime(2026, 1, 1, 1, tzinfo=timezone.utc), datetime(
            2026, 1, 1, tzinfo=timezone.utc,
        ),
    )
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).get_active(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
    )

    assert result['staging_expires_at'] == '2026-01-01T01:00:00+00:00'
    assert result['created_at'] == '2026-01-01T00:00:00+00:00'
    sql = cursor.execute.call_args.args[0]
    assert 'SELECT id, citation_table_name, source_sha256' in sql
    assert 'encrypted_staging_locator' not in sql
    assert 'created_by = %s' in sql
    assert 'cancelled_at IS NULL' in sql
    assert 'committed_batch_id IS NULL' in sql
    assert 'staging_expires_at > CURRENT_TIMESTAMP' in sql


@pytest.mark.asyncio
async def test_commit_decrypts_owned_staging_and_delegates_atomic_transaction() -> None:
    storage = MemoryStorage()
    repository = Mock()
    service = CitationImportPreviewService(
        storage, repository, secret_key='unit-test-secret',
    )
    preview_id = '00000000-0000-0000-0000-000000000001'
    locator = 'test-storage/citation-import-previews/sr-1/preview.fernet'
    source = b'Title,Abstract\nFirst,Summary\n'
    storage.contents[locator] = service._fernet.encrypt(
        json.dumps({
            'filename': 'citations.csv', 'source_format': 'csv',
            'raw_file_base64': __import__('base64').b64encode(source).decode(),
            'normalized_rows': [{'Title': 'First', 'Abstract': 'Summary'}],
        }).encode(),
    )
    repository.get_staging_locator.return_value = locator
    repository.commit.return_value = {
        'id': preview_id, 'batch_id': '00000000-0000-0000-0000-000000000002', 'idempotent': False,
        'inserted_count': 1, 'existing_exact_match_count': 0, 'invalid_count': 0,
    }

    result = await service.commit(
        preview_id=preview_id, sr_id='sr-1', actor_id='owner@example.test',
        approved_mapping={'title': 'Title', 'abstract': 'Abstract'},
    )

    assert result['inserted_count'] == 1
    repository.get_staging_locator.assert_called_once_with(
        preview_id, 'sr-1', 'owner@example.test',
    )
    staged_payload = repository.commit.call_args.args[4]
    assert staged_payload['normalized_rows'] == [
        {'Title': 'First', 'Abstract': 'Summary'},
    ]


@pytest.mark.asyncio
async def test_commit_does_not_decrypt_or_mutate_when_preview_is_not_owned() -> None:
    repository = Mock()
    repository.get_staging_locator.return_value = None
    service = CitationImportPreviewService(
        MemoryStorage(), repository, secret_key='unit-test-secret',
    )

    with pytest.raises(LookupError, match='not found'):
        await service.commit(
            preview_id='00000000-0000-0000-0000-000000000001', sr_id='sr-1', actor_id='other@example.test',
            approved_mapping={'title': 'Title', 'abstract': 'Abstract'},
        )

    repository.commit.assert_not_called()


def test_repository_commit_locks_preview_and_writes_batch_provenance() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [
        (
            'sr_1_citations', hashlib.sha256(b'raw').hexdigest(), {
                'title': 'Title', 'abstract': 'Abstract',
            },
            {'valid_for_commit': True}, None, None, datetime(
                2030, 1, 1, tzinfo=timezone.utc,
            ),
        ),
        ('sr_1_citations',), None, None, (42,),
    ]
    cursor.fetchall.return_value = [('id',), ('title',), ('abstract',)]
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
        {'title': 'Title', 'abstract': 'Abstract'},
        {
            'filename': 'citations.csv', 'source_format': 'csv',
            'raw_file_base64': __import__('base64').b64encode(b'raw').decode(),
            'normalized_rows': [{'Title': 'First', 'Abstract': 'Summary'}],
        },
    )

    assert result['inserted_count'] == 1
    connection.commit.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'FOR UPDATE' in sql
    assert 'INSERT INTO citation_import_batches' in sql
    assert 'INSERT INTO citation_import_batch_memberships' in sql
    assert 'INSERT INTO citation_identities' in sql
    assert 'INSERT INTO citation_audit_events' in sql
    assert 'UPDATE citation_import_previews SET committed_batch_id' in sql


def test_repository_commit_persists_namespaced_external_identities() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [
        (
            'sr_1_citations', hashlib.sha256(b'raw').hexdigest(), {
                'title': 'Title', 'abstract': 'Abstract',
            },
            {'valid_for_commit': True}, None, None, datetime(
                2030, 1, 1, tzinfo=timezone.utc,
            ),
        ),
        ('sr_1_citations',), None, None, None, (42,),
    ]
    cursor.fetchall.return_value = [('id',), ('title',), ('abstract',)]

    CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
        {'title': 'Title', 'abstract': 'Abstract'},
        {
            'raw_file_base64': __import__('base64').b64encode(b'raw').decode(),
            'normalized_rows': [{'Title': 'First', 'Abstract': 'Summary', 'PubMed ID': 'PMID: 123'}],
        },
    )

    external_id_calls = [
        call for call in cursor.execute.call_args_list
        if "'external_id'" in call.args[0]
    ]
    assert len(external_id_calls) == 1
    assert external_id_calls[0].args[1][-2:] == ('pubmed', '123')


def test_repository_commit_rejects_changed_mapping_and_rolls_back_before_writes() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = (
        'sr_1_citations', 'source-hash', {
            'title': 'Title',
            'abstract': 'Abstract',
        },
        {'valid_for_commit': True}, None, None, datetime(
            2030, 1, 1, tzinfo=timezone.utc,
        ),
    )
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    with pytest.raises(ValueError, match='exactly match'):
        CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
            '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
            {'title': 'Other', 'abstract': 'Abstract'}, {'normalized_rows': []},
        )

    connection.rollback.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'INSERT INTO citation_import_batches' not in sql
    assert 'INSERT INTO "sr_1_citations"' not in sql


def test_repository_commit_rejects_ambiguous_reconciliation_before_citation_writes() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = (
        'sr_1_citations', 'source-hash', {
            'title': 'Title',
            'abstract': 'Abstract',
        },
        {'valid_for_commit': True, 'reconciliation': {'counts': {'ambiguous': 1}}},
        None, None, datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    with pytest.raises(ValueError, match='ambiguous exact'):
        CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
            '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
            {'title': 'Title', 'abstract': 'Abstract'}, {'normalized_rows': []},
        )

    connection.rollback.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'INSERT INTO citation_import_batches' not in sql
    assert 'INSERT INTO "sr_1_citations"' not in sql


def test_repository_commit_returns_original_batch_result_for_idempotent_retry() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [
        (
            'sr_1_citations', hashlib.sha256(b'raw').hexdigest(), {
                'title': 'Title', 'abstract': 'Abstract',
            },
            {'valid_for_commit': True}, '00000000-0000-0000-0000-000000000002', None,
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        ),
        (3, 2, 1),
    ]
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
        {'title': 'Title', 'abstract': 'Abstract'}, {'normalized_rows': []},
    )

    assert result == {
        'id': '00000000-0000-0000-0000-000000000001',
        'batch_id': '00000000-0000-0000-0000-000000000002', 'idempotent': True,
        'inserted_count': 3, 'existing_exact_match_count': 2, 'invalid_count': 1,
    }
    connection.commit.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'INSERT INTO citation_import_batches' not in sql


def test_repository_commit_reuses_existing_committed_content_batch() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [
        (
            'sr_1_citations', hashlib.sha256(b'raw').hexdigest(), {
                'title': 'Title', 'abstract': 'Abstract',
            },
            {'valid_for_commit': True}, None, None, datetime(
                2030, 1, 1, tzinfo=timezone.utc,
            ),
        ),
        ('sr_1_citations',),
        ('00000000-0000-0000-0000-000000000002', 3, 2, 1),
    ]
    cursor.fetchall.return_value = [('id',), ('title',), ('abstract',)]
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
        {'title': 'Title', 'abstract': 'Abstract'},
        {
            'raw_file_base64': __import__('base64').b64encode(
                b'raw',
            ).decode(), 'normalized_rows': [],
        },
    )

    assert result['batch_id'] == '00000000-0000-0000-0000-000000000002'
    assert result['idempotent'] is True
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'FROM citation_import_batches' in sql
    assert 'INSERT INTO citation_import_batches' not in sql


def test_repository_commit_creates_and_registers_initial_dataset_atomically() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [
        (
            None, hashlib.sha256(b'raw').hexdigest(), {
                'title': 'Title', 'abstract': 'Abstract',
            },
            {'valid_for_commit': True}, None, None, datetime(
                2030, 1, 1, tzinfo=timezone.utc,
            ),
        ),
        (None,), None, None, (17,),
    ]
    cursor.fetchall.return_value = [('id',), ('title',), ('abstract',)]
    cursor.rowcount = 1
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    result = CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
        '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
        {'title': 'Title', 'abstract': 'Abstract'},
        {
            'filename': 'initial.csv', 'source_format': 'csv',
            'raw_file_base64': __import__('base64').b64encode(b'raw').decode(),
            'normalized_rows': [{'Title': 'First', 'Abstract': 'Summary'}],
        },
    )

    assert result['inserted_count'] == 1
    connection.commit.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'FROM systematic_reviews WHERE id = %s FOR UPDATE' in sql
    assert 'CREATE TABLE "sr_' in sql
    assert 'INSERT INTO citation_import_batches' in sql
    assert 'UPDATE systematic_reviews' in sql
    assert 'screening_db = jsonb_build_object' in sql
    assert 'DROP TABLE' not in sql


def test_repository_initial_commit_rejects_concurrent_dataset_and_rolls_back() -> None:
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [
        (
            None, hashlib.sha256(b'raw').hexdigest(), {
                'title': 'Title', 'abstract': 'Abstract',
            },
            {'valid_for_commit': True}, None, None, datetime(
                2030, 1, 1, tzinfo=timezone.utc,
            ),
        ),
        ('another_citation_table',),
    ]
    from api.services.citation_import_preview_service import CitationImportPreviewRepository

    with pytest.raises(ValueError, match='created while'):
        CitationImportPreviewRepository(connection_provider=Mock(conn=connection)).commit(
            '00000000-0000-0000-0000-000000000001', 'sr-1', 'owner@example.test',
            {'title': 'Title', 'abstract': 'Abstract'},
            {
                'raw_file_base64': __import__('base64').b64encode(
                    b'raw',
                ).decode(), 'normalized_rows': [],
            },
        )

    connection.rollback.assert_called_once_with()
    sql = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
    assert 'CREATE TABLE' not in sql
    assert 'UPDATE systematic_reviews' not in sql
