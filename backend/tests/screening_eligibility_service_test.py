from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock

if 'psycopg' not in sys.modules:
    psycopg = types.ModuleType('psycopg')
    psycopg.connect = Mock()
    psycopg_rows = types.ModuleType('psycopg.rows')
    psycopg_rows.dict_row = Mock()
    psycopg.rows = psycopg_rows
    sys.modules['psycopg'] = psycopg
    sys.modules['psycopg.rows'] = psycopg_rows

from api.services.screening_eligibility_service import ScreeningEligibilityService
from api.services.screening_eligibility_service import compute_screening_decisions


CRITERIA = {
    'l1': {'questions': ['Relevant population?']},
    'l2': {'questions': ['Eligible study design?']},
}


class ScreeningDecisionTests(unittest.TestCase):
    def test_human_answer_overrides_ai_answer(self) -> None:
        row = {
            'human_relevant_population': {'selected': 'Include'},
            'llm_relevant_population': {'selected': 'Exclude'},
            'human_eligible_study_design': {'selected': 'Include'},
        }

        self.assertEqual(
            compute_screening_decisions(row, CRITERIA),
            ('include', 'include'),
        )

    def test_ai_answer_is_used_when_human_answer_is_missing(self) -> None:
        row = {
            'llm_relevant_population': '{"selected": "Include"}',
            'llm_eligible_study_design': {'selected': 'Include'},
        }

        self.assertEqual(
            compute_screening_decisions(row, CRITERIA),
            ('include', 'include'),
        )

    def test_critical_ai_answer_does_not_override_screening_ai_answer(self) -> None:
        row = {
            'llm_relevant_population': {
                'selected': 'Include',
                'critical': {'selected': 'Exclude'},
            },
            'llm_eligible_study_design': {'selected': 'Include'},
        }

        self.assertEqual(
            compute_screening_decisions(row, CRITERIA),
            ('include', 'include'),
        )

    def test_l2_decision_is_cumulative_and_missing_answers_exclude(self) -> None:
        row = {'human_relevant_population': {'selected': 'Include'}}

        self.assertEqual(
            compute_screening_decisions(row, CRITERIA),
            ('include', 'exclude'),
        )


class ScreeningEligibilityServiceTests(unittest.TestCase):
    def test_l2_repairs_decisions_before_filtering(self) -> None:
        repository = Mock()
        repository.list_citation_ids.return_value = [4, 9]
        service = ScreeningEligibilityService(repository)

        result = service.list_eligible_ids(
            criteria=CRITERIA,
            table_name='screening_table',
            target_stage='l2',
        )

        self.assertEqual(result, [4, 9])
        self.assertEqual(
            repository.method_calls,
            [
                unittest.mock.call.backfill_human_decisions(
                    CRITERIA, 'screening_table',
                ),
                unittest.mock.call.list_citation_ids('l1', 'screening_table'),
            ],
        )

    def test_l1_does_not_run_unnecessary_repair(self) -> None:
        repository = Mock()
        repository.list_citation_ids.return_value = [1, 2]
        service = ScreeningEligibilityService(repository)

        result = service.list_eligible_ids(
            criteria=CRITERIA,
            table_name='screening_table',
            target_stage='l1',
        )

        self.assertEqual(result, [1, 2])
        repository.backfill_human_decisions.assert_not_called()
        repository.list_citation_ids.assert_called_once_with(
            None, 'screening_table',
        )

    def test_l2_read_only_scope_does_not_repair_decisions(self) -> None:
        repository = Mock()
        repository.list_citation_ids.return_value = [4, 9]
        service = ScreeningEligibilityService(repository)

        result = service.list_eligible_ids(
            criteria=CRITERIA,
            table_name='screening_table',
            target_stage='l2',
            repair_decisions=False,
        )

        self.assertEqual(result, [4, 9])
        repository.backfill_human_decisions.assert_not_called()
        repository.list_citation_ids.assert_called_once_with(
            'l1', 'screening_table',
        )

    def test_extract_read_only_scope_uses_l2_decisions(self) -> None:
        repository = Mock()
        repository.list_citation_ids.return_value = [12]
        service = ScreeningEligibilityService(repository)

        result = service.list_eligible_ids(
            criteria=CRITERIA,
            table_name='screening_table',
            target_stage='extract',
            repair_decisions=False,
        )

        self.assertEqual(result, [12])
        repository.backfill_human_decisions.assert_not_called()
        repository.list_citation_ids.assert_called_once_with(
            'l2', 'screening_table',
        )

    def test_read_only_scope_is_not_affected_by_repair_failure(self) -> None:
        repository = Mock()
        repository.backfill_human_decisions.side_effect = RuntimeError(
            'repair failed',
        )
        repository.list_citation_ids.return_value = [4]
        service = ScreeningEligibilityService(repository)

        result = service.list_eligible_ids(
            criteria=CRITERIA,
            table_name='screening_table',
            target_stage='l2',
            repair_decisions=False,
        )

        self.assertEqual(result, [4])
        repository.backfill_human_decisions.assert_not_called()

    def test_repair_failure_is_not_hidden_as_an_empty_scope(self) -> None:
        repository = Mock()
        repository.backfill_human_decisions.side_effect = RuntimeError(
            'repair failed',
        )
        service = ScreeningEligibilityService(repository)

        with self.assertRaisesRegex(RuntimeError, 'repair failed'):
            service.list_eligible_ids(
                criteria=CRITERIA,
                table_name='screening_table',
                target_stage='l2',
            )

        repository.list_citation_ids.assert_not_called()


if __name__ == '__main__':
    unittest.main()
