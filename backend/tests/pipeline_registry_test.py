from __future__ import annotations

import unittest
from typing import cast

from api.jobs.pipelines.base import PipelineDefinition
from api.jobs.pipelines.base import PipelineOutcome
from api.jobs.pipelines.registry import PipelineRegistry


class FakePipeline:
    pipeline_key = 'fake'


class PipelineRegistryTests(unittest.TestCase):
    def test_register_and_get(self):
        registry = PipelineRegistry()
        pipeline = FakePipeline()
        registry.register(cast(PipelineDefinition, pipeline))
        self.assertIs(registry.get('FAKE'), pipeline)
        self.assertEqual(registry.keys, ('fake',))

    def test_duplicate_registration_is_rejected(self):
        registry = PipelineRegistry()
        registry.register(cast(PipelineDefinition, FakePipeline()))
        with self.assertRaises(ValueError):
            registry.register(cast(PipelineDefinition, FakePipeline()))

    def test_unknown_pipeline_is_rejected(self):
        with self.assertRaisesRegex(KeyError, 'Unsupported pipeline_key'):
            PipelineRegistry().get('missing')

    def test_outcomes_map_to_generic_counters(self):
        self.assertEqual(PipelineOutcome('done').counts, (1, 0, 0))
        self.assertEqual(PipelineOutcome('skipped').counts, (0, 1, 0))
        self.assertEqual(PipelineOutcome('failed').counts, (0, 0, 1))


if __name__ == '__main__':
    unittest.main()
