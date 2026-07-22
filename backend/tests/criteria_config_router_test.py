from __future__ import annotations

import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from api.criteria.models import CriteriaConfigV2
from api.sr.router import CriteriaConfigSaveRequest
from api.sr.router import CriteriaYamlImportRequest
from api.sr.router import get_criteria_config
from api.sr.router import import_criteria_yaml
from api.sr.router import save_criteria_config
from fastapi import HTTPException


EMPTY_CONFIG = {
    'schema_version': 2,
    'citation_fields': {'l1_include': []},
    'l1': [],
    'l2': [],
    'parameters': [],
}
USER = {'id': 'owner-id', 'email': 'owner@example.test'}


class CriteriaConfigRouterTests(unittest.IsolatedAsyncioTestCase):
    @patch('api.sr.router._load_criteria_review', new_callable=AsyncMock)
    async def test_get_normalizes_legacy_without_persisting(self, load_review: AsyncMock) -> None:
        load_review.return_value = {
            'criteria_revision': 4,
            'criteria': {
                'include': ['Title'],
                'criteria': {'Eligible?': {'Yes': 'Include', 'No (exclude)': 'Exclude'}},
            },
        }

        response = await get_criteria_config('review-id', USER)

        self.assertEqual(response['revision'], 4)
        self.assertEqual(response['criteria']['schema_version'], 2)
        self.assertEqual(response['migration']['status'], 'preview')
        self.assertTrue(
            response['migration']
            ['fingerprint'].startswith('sha256:'),
        )

    @patch('api.sr.router._load_criteria_review', new_callable=AsyncMock)
    async def test_import_returns_422_for_invalid_yaml(self, load_review: AsyncMock) -> None:
        load_review.return_value = {'criteria_revision': 0}

        with self.assertRaises(HTTPException) as caught:
            await import_criteria_yaml(
                'review-id', CriteriaYamlImportRequest(
                    criteria_yaml='- not\n- a mapping',
                ), USER,
            )

        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(
            caught.exception.detail['errors'][0]['code'], 'invalid_criteria',
        )

    @patch('api.sr.router._load_criteria_review', new_callable=AsyncMock)
    async def test_save_requires_force_when_screening_data_exists(self, load_review: AsyncMock) -> None:
        load_review.return_value = {
            'screening_db': {'table_name': 'citations'},
        }
        payload = CriteriaConfigSaveRequest(
            expected_revision=2,
            force=False,
            criteria=CriteriaConfigV2.model_validate(EMPTY_CONFIG),
        )

        with self.assertRaises(HTTPException) as caught:
            await save_criteria_config('review-id', payload, USER)

        self.assertEqual(caught.exception.status_code, 409)

    @patch('api.sr.router._load_criteria_review', new_callable=AsyncMock)
    async def test_save_requires_matching_legacy_migration_fingerprint(self, load_review: AsyncMock) -> None:
        load_review.return_value = {
            'criteria': {
                'criteria': {'Eligible?': {'Yes': 'Include', 'No (exclude)': 'Exclude'}},
            },
        }
        payload = CriteriaConfigSaveRequest(
            expected_revision=0,
            criteria=CriteriaConfigV2.model_validate(EMPTY_CONFIG),
        )

        with self.assertRaises(HTTPException) as caught:
            await save_criteria_config('review-id', payload, USER)

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            caught.exception.detail['code'], 'migration_confirmation_required',
        )
        self.assertTrue(
            caught.exception.detail['fingerprint'].startswith('sha256:'),
        )


if __name__ == '__main__':
    unittest.main()
