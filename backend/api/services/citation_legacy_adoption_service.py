"""Safe, idempotent adoption of existing dynamic citation tables."""
from __future__ import annotations

import re
import uuid
from typing import Any

try:
    from .postgres_auth import postgres_server
# Optional psycopg2 dependency in unit-test tooling.
except ModuleNotFoundError:
    postgres_server = None


_LEGACY_BATCH_NAMESPACE = uuid.UUID('c6e5bd06-a30c-47bb-a6cf-7b8a993f7925')
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


def _validate_table_name(name: str) -> str:
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f'Invalid citation_table_name: {name!r}')
    return name


class CitationLegacyAdoptionService:
    """Backfill immutable provenance without altering legacy citation rows."""

    def __init__(self, connection_provider=None):
        self.connection_provider = connection_provider

    def _connection(self):
        provider = self.connection_provider or postgres_server
        if provider is None:
            raise RuntimeError('PostgreSQL driver is not available')
        return provider.conn

    @staticmethod
    def legacy_batch_id(sr_id: str, citation_table_name: str) -> str:
        return str(
            uuid.uuid5(
                _LEGACY_BATCH_NAMESPACE, f'{sr_id}\x1f{citation_table_name}',
            ),
        )

    def adopt(
        self, sr_id: str, citation_table_name: str, actor_id: str,
        *, dry_run: bool = False,
    ) -> dict[str, Any]:
        """Adopt one configured table, retaining its name and citation IDs.

        The SR-to-table relationship and physical ``id`` column are verified in
        this transaction before provenance is written. Repeated calls only add
        missing membership rows and always return the deterministic batch ID.
        """
        table_name = _validate_table_name(citation_table_name)
        if not sr_id or not actor_id:
            raise ValueError('sr_id and actor_id are required')

        conn = self._connection()
        cur = conn.cursor()
        batch_id = self.legacy_batch_id(sr_id, table_name)
        try:
            cur.execute(
                """SELECT 1 FROM systematic_reviews
                   WHERE id = %s AND screening_db ->> 'table_name' = %s""",
                (sr_id, table_name),
            )
            if not cur.fetchone():
                raise ValueError(
                    'Citation table is not configured for this systematic review',
                )
            cur.execute(
                """SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = %s
                     AND column_name = 'id'""",
                (table_name,),
            )
            if not cur.fetchone():
                raise ValueError(
                    'Citation table does not exist or has no id column',
                )
            cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            citation_count = int(cur.fetchone()[0])
            if dry_run:
                conn.rollback()
                return {
                    'batch_id': batch_id, 'citation_count': citation_count,
                    'memberships_created': 0, 'dry_run': True,
                }

            cur.execute(
                """INSERT INTO citation_import_batches
                    (id, sr_id, citation_table_name, source_type, source_metadata,
                     display_filename, state, inserted_count, created_by, committed_at)
                   VALUES (%s, %s, %s, 'legacy_initial_dataset',
                           '{"source":"legacy_unknown"}'::jsonb,
                           'Legacy initial dataset', 'committed', 0, %s,
                           CURRENT_TIMESTAMP)
                   ON CONFLICT (id) DO NOTHING""",
                (batch_id, sr_id, table_name, actor_id),
            )
            cur.execute(
                f"""INSERT INTO citation_import_batch_memberships
                    (batch_id, sr_id, citation_table_name, citation_id, outcome)
                   SELECT %s, %s, %s, id, 'inserted' FROM \"{table_name}\"
                   ON CONFLICT (batch_id, citation_id) DO NOTHING""",
                (batch_id, sr_id, table_name),
            )
            memberships_created = cur.rowcount
            cur.execute(
                """INSERT INTO citation_audit_events
                    (id, sr_id, citation_table_name, batch_id, event_type, actor_id, details)
                   VALUES (%s, %s, %s, %s, 'legacy_table_adopted', %s,
                           jsonb_build_object('citation_count', %s))
                   ON CONFLICT (batch_id, event_type) WHERE event_type = 'legacy_table_adopted'
                   DO NOTHING""",
                (
                    str(uuid.uuid4()), sr_id, table_name,
                    batch_id, actor_id, citation_count,
                ),
            )
            conn.commit()
            return {
                'batch_id': batch_id, 'citation_count': citation_count,
                'memberships_created': memberships_created, 'dry_run': False,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


citation_legacy_adoption_service = CitationLegacyAdoptionService()
