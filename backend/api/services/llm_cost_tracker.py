from __future__ import annotations

import logging
import uuid
from datetime import datetime
from datetime import timezone
from decimal import Decimal

from .postgres_auth import postgres_server

logger = logging.getLogger(__name__)


class LLMCostTracker:
    def __init__(self):
        self._table_ready = False

    async def ensure_table(self):
        if self._table_ready:
            return

        async with postgres_server.aconn() as conn:
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS llm_cost_usage (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        sr_id TEXT,
                        model TEXT NOT NULL,
                        prompt_tokens INT NOT NULL,
                        completion_tokens INT NOT NULL,
                        total_tokens INT NOT NULL,
                        cost_cad NUMERIC(12,6) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """,
                )
                await conn.commit()
                logger.info('Ensured llm_cost_usage table exists')
            except Exception as e:
                logger.exception(
                    'Failed to ensure llm_cost_usage table exists: %s', e,
                )
                raise

        self._table_ready = True

    async def record_attempt(
        self,
        *,
        user_id: str,
        sr_id: str | None = None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_cad: Decimal,
        created_at: datetime | None = None,
    ):

        await self.ensure_table()

        if created_at is None:
            created_at = datetime.now(timezone.utc)

        async with postgres_server.aconn() as conn:
            await conn.execute(
                """
                INSERT INTO llm_cost_usage (
                    id,
                    user_id,
                    sr_id,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    cost_cad,
                    created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    sr_id,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    cost_cad,
                    created_at,
                ),
            )
            await conn.commit()


llm_cost_tracker = LLMCostTracker()
