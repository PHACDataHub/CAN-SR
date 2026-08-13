import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import ScreeningMetricsPanel from './ScreeningMetricsPanel'

it('applies and commits a recommended criterion threshold', async () => {
  const user = userEvent.setup()
  const onCriterionThresholdChange = vi.fn()
  const onCriterionThresholdCommit = vi.fn()

  render(
    <ScreeningMetricsPanel
      filterMode="all"
      onFilterModeChange={vi.fn()}
      criterionMetrics={[
        {
          criterion_key: 'population',
          label: 'Human population',
          threshold: 0.8,
          total_citations: 10,
          has_run_count: 10,
          low_confidence_count: 0,
          critical_disagreement_count: 0,
          confident_exclude_count: 0,
          needs_human_review_count: 2,
        },
      ]}
      calibration={[
        {
          criterion_key: 'population',
          label: 'Human population',
          validated_n: 10,
          recommended_threshold: 0.72,
          curve: [],
          histogram: [],
        },
      ]}
      onCriterionThresholdChange={onCriterionThresholdChange}
      onCriterionThresholdCommit={onCriterionThresholdCommit}
    />,
  )

  await user.click(
    screen.getByRole('button', {
      name: 'Use recommended threshold (72%)',
    }),
  )

  expect(onCriterionThresholdChange).toHaveBeenCalledWith('population', 0.72)
  expect(onCriterionThresholdCommit).toHaveBeenCalledWith('population', 0.72)
})
