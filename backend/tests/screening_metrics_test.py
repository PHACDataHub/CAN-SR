from __future__ import annotations

from api.screen.router import _human_answer_column
from api.screen.router import _screening_metric_values
from api.screen.router import ScreeningMetricsCriterion


def test_metric_human_columns_are_stage_specific() -> None:
    assert _human_answer_column(
        'l1', 'primary_research',
    ) == 'human_l1_primary_research'
    assert _human_answer_column(
        'l2', 'primary_research',
    ) == 'human_l2_primary_research'


def test_metric_values_include_accuracy_and_confusion_metrics() -> None:
    values = _screening_metric_values({
        'human_total_count': 4,
        'human_agree_count': 3,
        'human_total_count_all': 5,
        'human_agree_count_all': 4,
        'crit_total_count': 2,
        'crit_agree_count': 1,
        'cm_tp': 3,
        'cm_fp': 1,
        'cm_fn': 2,
        'cm_tn': 4,
    })

    assert values['accuracy'] == 0.75
    assert values['accuracy_all'] == 0.8
    assert values['accuracy_critical_agent'] == 0.5
    assert values['f1_score'] == 0.6666666666666666
    assert values['precision'] == 0.75
    assert values['recall'] == 0.6
    assert values['npv'] == 4 / 6
    assert values['confusion_matrix'] == {'tp': 3, 'fp': 1, 'fn': 2, 'tn': 4}


def test_metric_pydantic_model_retains_calculated_fields() -> None:
    model = ScreeningMetricsCriterion(
        criterion_key='primary_research', label='Primary research', threshold=0.8,
        total_citations=10, has_run_count=10, low_confidence_count=1,
        critical_disagreement_count=1, confident_exclude_count=2,
        needs_human_review_count=3, accuracy=0.75, accuracy_all=0.8,
        f1_score=2 / 3, precision=0.75, recall=0.6, npv=4 / 6,
        confusion_matrix={'tp': 3, 'fp': 1, 'fn': 2, 'tn': 4},
    )
    dumped = model.model_dump()
    assert dumped['accuracy'] == 0.75
    assert dumped['f1_score'] == 2 / 3
    assert dumped['confusion_matrix']['tp'] == 3
