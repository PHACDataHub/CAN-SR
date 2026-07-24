from __future__ import annotations

import unittest
from pathlib import Path

from api.criteria.models import CriteriaConfigV2
from api.criteria.service import CriteriaConfigurationService
from pydantic import ValidationError


class CriteriaConfigurationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CriteriaConfigurationService()

    def test_v2_yaml_round_trip_is_deterministic(self) -> None:
        config = {
            'schema_version': 2,
            'citation_fields': {'l1_include': ['Title', 'Abstract'], 'doi': 'DOI'},
            'l1': [{
                'id': 'q_primary',
                'question': 'Primary research?',
                'answers': [
                    {'id': 'yes', 'label': 'Yes', 'decision': 'include'},
                    {'id': 'no_answer', 'label': 'No', 'decision': 'exclude'},
                ],
                'trigger': {'all': []},
            }],
            'l2': [],
            'parameters': [{
                'id': 'p_design',
                'name': 'Design',
                'description': 'Reported study design.',
                'type': 'selection',
                'selection_mode': 'single',
                'options': [{'id': 'cohort', 'label': 'Cohort'}],
                'trigger': {'all': [{'source_item_id': 'q_primary', 'option_id': 'yes'}]},
            }],
        }

        first = self.service.export_yaml(config)
        loaded = self.service.parse_yaml(first)
        second = self.service.export_yaml(loaded.criteria)

        self.assertEqual(first, second)
        self.assertEqual(
            loaded.criteria.model_dump(
                mode='json',
            ), CriteriaConfigV2.model_validate(config).model_dump(mode='json'),
        )

    def test_forward_and_text_parameter_trigger_sources_are_rejected(self) -> None:
        base = {
            'schema_version': 2, 'citation_fields': {}, 'l1': [], 'l2': [],
            'parameters': [
                {
                    'id': 'p_text', 'name': 'Text', 'description': 'Text value', 'type': 'text',
                },
                {
                    'id': 'p_later', 'name': 'Later', 'description': 'Later value', 'type': 'text',
                    'trigger': {'all': [{'source_item_id': 'p_text', 'option_id': 'anything'}]},
                },
            ],
        }

        with self.assertRaisesRegex(ValidationError, 'text parameters cannot be trigger sources'):
            CriteriaConfigV2.model_validate(base)

        base['parameters'][0]['trigger'] = {
            'all': [{'source_item_id': 'p_later', 'option_id': 'anything'}],
        }
        with self.assertRaisesRegex(ValidationError, 'must reference an earlier item'):
            CriteriaConfigV2.model_validate(base)

    def test_representative_legacy_yaml_migrates_deterministically(self) -> None:
        path = Path(__file__).parents[1] / \
            'api/sr/criteria_config_measles_updated.yaml'
        content = path.read_text(encoding='utf-8')

        first = self.service.parse_yaml(content)
        second = self.service.parse_yaml(content)

        self.assertEqual(first.criteria, second.criteria)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.stats.l1, 3)
        self.assertEqual(first.stats.l2, 1)
        self.assertGreater(first.stats.parameters, 1)
        self.assertTrue(first.requires_confirmation)
        self.assertIn(
            'decision_inferred_exclude', {
                item.code for item in first.diagnostics
            },
        )

    def test_legacy_collision_ids_are_stable_and_unique(self) -> None:
        legacy = '''
criteria:
  Same question:
    "Yes": Include
    "No (exclude)": Exclude
l2_criteria:
  Same question:
    "Yes": Include
    "No (exclude)": Exclude
parameters:
  Category:
    A/B: First
    A B: Second
'''
        result = self.service.parse_yaml(legacy)
        item_ids = [
            *[item.id for item in result.criteria.l1],
            *[item.id for item in result.criteria.l2],
            *[item.id for item in result.criteria.parameters],
        ]

        self.assertEqual(len(item_ids), len(set(item_ids)))
        self.assertEqual(item_ids[-1], f'{item_ids[-2]}_2')

    def test_mixed_v2_and_legacy_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, 'cannot contain legacy keys'):
            self.service.normalize({
                'schema_version': 2, 'citation_fields': {}, 'l1': [], 'l2': [],
                'parameters': [], 'include': ['Title'],
            })

    def test_projection_retains_legacy_arrays_and_adds_stable_items(self) -> None:
        migrated = self.service.normalize({
            'include': ['Title'],
            'criteria': {'Eligible?': {'Yes': 'Include it', 'No (exclude)': 'Exclude it'}},
            'parameters': {'Group': {'Rate': 'A reported rate'}},
        })

        projection = self.service.build_compatibility_projection(
            migrated.criteria,
        )

        self.assertEqual(projection['schema_version'], 2)
        self.assertEqual(projection['l1']['questions'], ['Eligible?'])
        self.assertEqual(projection['l1']['include'], ['Title'])
        self.assertEqual(
            projection['l1']['items']
            [0]['id'], migrated.criteria.l1[0].id,
        )
        self.assertEqual(
            projection['parameters']['items']
            [0]['id'], migrated.criteria.parameters[0].id,
        )


if __name__ == '__main__':
    unittest.main()
