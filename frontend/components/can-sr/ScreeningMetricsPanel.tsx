import React from 'react'

export type ScreeningMetricsStats = {
  scopeLabel?: string
  total: number
  needsValidation: number
  validated: number
  unvalidated: number
}

export type ScreeningMetricsSummary = {
  step: string
  total_citations: number
  validated_all: number
  unvalidated_all: number
  needs_review_total: number
  validated_needs_review: number
  unvalidated_needs_review: number
  not_screened_yet?: number
  auto_excluded?: number
}

export type ScreeningCriterionMetrics = {
  criterion_key: string
  label: string
  threshold: number
  total_citations: number
  has_run_count: number
  low_confidence_count: number
  critical_disagreement_count: number
  confident_exclude_count: number
  needs_human_review_count: number
  accuracy?: number | null
  accuracy_all?: number | null
  accuracy_critical_agent?: number | null
  f1_score?: number | null
  precision?: number | null
  recall?: number | null
  npv?: number | null
  confusion_matrix?: { tp: number; fp: number; fn: number; tn: number } | null
  queue_confusion_matrix?: {
    tp: number
    fp: number
    fn: number
    tn: number
  } | null
  human_total_count_all?: number | null
}

export type CalibrationPoint = {
  threshold: number
  tp: number
  fp: number
  fn: number
  tn: number
  precision?: number | null
  recall?: number | null
  fpr?: number | null
  tpr?: number | null
  workload_reduction?: number | null
}

export type CalibrationHistogramBin = {
  bin_start: number
  bin_end: number
  agree: number
  disagree: number
}

export type LiveConfidenceHistogramBin = {
  bin_start: number
  bin_end: number
  unlabelled: number
  agree: number
  disagree: number
}

export type LiveConfidenceHistogramCriterion = {
  criterion_key: string
  label: string
  histogram: LiveConfidenceHistogramBin[]
}

export type LiveConfidenceHistogramResponse = {
  sr_id: string
  step: string
  bins: number
  criteria: LiveConfidenceHistogramCriterion[]
}

export type CalibrationCriterion = {
  criterion_key: string
  label: string
  validated_n: number
  recommended_threshold?: number | null
  recommended_reason?: string | null
  curve: CalibrationPoint[]
  histogram: CalibrationHistogramBin[]
}

export type ScreeningMetricsPanelProps = {
  title?: string
  /**
   * Legacy single threshold (Phase 1). Prefer criterionMetrics/summary instead.
   */
  threshold?: number
  onThresholdChange?: (v: number) => void

  /**
   * Phase 2: per-criterion thresholds + metrics.
   */
  summary?: ScreeningMetricsSummary
  criterionMetrics?: ScreeningCriterionMetrics[]
  onCriterionThresholdChange?: (criterionKey: string, v: number) => void
  onCriterionThresholdCommit?: (criterionKey: string, v: number) => void

  /**
   * Phase 2A: calibration curves + recommended thresholds (validated set).
   */
  calibration?: CalibrationCriterion[]

  /** Optional: open a larger reporting drawer. */
  onOpenDetails?: () => void

  /**
   * Optional save controls for per-criterion thresholds.
   * When provided, the save button will be shown in the Criteria header.
   */
  thresholdsDirty?: boolean
  savingThresholds?: boolean
  onSaveThresholds?: () => void

  /**
   * Some layouts want the Filter control above the main list view instead of in the metrics panel.
   */
  showFilter?: boolean

  filterMode: 'needs' | 'validated' | 'unvalidated' | 'not_screened' | 'all'
  onFilterModeChange: (
    v: 'needs' | 'validated' | 'unvalidated' | 'not_screened' | 'all',
  ) => void
  stats?: ScreeningMetricsStats
}

/**
 * Phase 1/2 bridge component.
 *
 * Phase 1: provides the control surface (threshold + filter) and basic counts.
 * Phase 2: will additionally display backend metrics (accuracy/curves/recommended threshold).
 */
export default function ScreeningMetricsPanel({
  title = 'Metrics',
  threshold,
  onThresholdChange,
  summary,
  criterionMetrics,
  onCriterionThresholdChange,
  onCriterionThresholdCommit,
  calibration,
  onOpenDetails,
  thresholdsDirty,
  savingThresholds,
  onSaveThresholds,
  showFilter = true,
  filterMode,
  onFilterModeChange,
  stats: _stats,
}: ScreeningMetricsPanelProps) {
  const [sliderPercents, setSliderPercents] = React.useState<
    Record<string, number>
  >({})
  const pendingSliderPercents = React.useRef<Record<string, number>>({})

  React.useEffect(() => {
    if (!criterionMetrics?.length) return
    setSliderPercents((previous) => {
      const next = { ...previous }
      for (const criterion of criterionMetrics) {
        const incoming = Math.round(
          Math.max(0, Math.min(1, criterion.threshold)) * 100,
        )
        const pending = pendingSliderPercents.current[criterion.criterion_key]
        if (pending === undefined || incoming === pending) {
          next[criterion.criterion_key] = incoming
          if (incoming === pending)
            delete pendingSliderPercents.current[criterion.criterion_key]
        }
      }
      return next
    })
  }, [criterionMetrics])

  // Kept for backwards-compatibility with callers that still compute page-local stats.
  void _stats

  const calibByKey = React.useMemo(() => {
    const m = new Map<string, CalibrationCriterion>()
    for (const c of calibration || []) m.set(c.criterion_key, c)
    return m
  }, [calibration])

  const total = summary?.total_citations ?? 0
  const validatedAll = summary?.validated_all ?? 0
  const notScreened = summary?.not_screened_yet ?? 0

  // Human review queue is a subset of unvalidated; "not screened yet" should not be part of the queue.
  const queueTotal = summary?.needs_review_total ?? 0
  const queueValidated = summary?.validated_needs_review ?? 0
  const queueRemaining = Math.max(0, queueTotal - queueValidated)

  // Everything that is NOT validated, NOT in the remaining queue, and NOT not-screened.
  // (Typically: confident excludes + confident includes at current thresholds.)
  const resolvedRemaining = Math.max(
    0,
    total - validatedAll - queueRemaining - notScreened,
  )

  const validatedPct = total > 0 ? (validatedAll / total) * 100 : 0
  const queueRemainingPct = total > 0 ? (queueRemaining / total) * 100 : 0
  const resolvedPct = total > 0 ? (resolvedRemaining / total) * 100 : 0
  const notScreenedPct = total > 0 ? (notScreened / total) * 100 : 0

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
          {onOpenDetails ? (
            <button
              type="button"
              onClick={onOpenDetails}
              className="rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] text-gray-700 hover:bg-gray-50"
            >
              Details
            </button>
          ) : null}
        </div>

        {/* Headline metrics */}
        {criterionMetrics?.length ? (
          (() => {
            const accVals = criterionMetrics
              .filter((c) => typeof c.accuracy_all === 'number')
              .map((c) => c.accuracy_all as number)
            const avgAcc = accVals.length
              ? Math.round(
                  (accVals.reduce((a, b) => a + b, 0) / accVals.length) * 100,
                )
              : null
            const f1Vals = criterionMetrics
              .filter((c) => typeof c.f1_score === 'number')
              .map((c) => c.f1_score as number)
            const avgF1 = f1Vals.length
              ? Math.round(
                  (f1Vals.reduce((a, b) => a + b, 0) / f1Vals.length) * 100,
                )
              : null
            const precVals = criterionMetrics
              .filter((c) => typeof c.precision === 'number')
              .map((c) => c.precision as number)
            const avgPrec = precVals.length
              ? Math.round(
                  (precVals.reduce((a, b) => a + b, 0) / precVals.length) * 100,
                )
              : null
            const recVals = criterionMetrics
              .filter((c) => typeof c.recall === 'number')
              .map((c) => c.recall as number)
            const avgRec = recVals.length
              ? Math.round(
                  (recVals.reduce((a, b) => a + b, 0) / recVals.length) * 100,
                )
              : null
            const screened = total - notScreened
            const wr =
              screened > 0
                ? Math.round((1 - queueTotal / screened) * 100)
                : null
            return (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1.5 rounded-md bg-emerald-50 px-2 py-1">
                  <span className="text-[10px] text-emerald-600">Acc</span>
                  <span className="text-xs font-semibold text-emerald-900">
                    {avgAcc === null ? '—' : `${avgAcc}%`}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 rounded-md bg-indigo-50 px-2 py-1">
                  <span className="text-[10px] text-indigo-600">F1</span>
                  <span className="text-xs font-semibold text-indigo-900">
                    {avgF1 === null ? '—' : `${avgF1}%`}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 rounded-md bg-sky-50 px-2 py-1">
                  <span className="text-[10px] text-sky-600">Prec</span>
                  <span className="text-xs font-semibold text-sky-900">
                    {avgPrec === null ? '—' : `${avgPrec}%`}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 rounded-md bg-violet-50 px-2 py-1">
                  <span className="text-[10px] text-violet-600">Recall</span>
                  <span className="text-xs font-semibold text-violet-900">
                    {avgRec === null ? '—' : `${avgRec}%`}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-1">
                  <span className="text-[10px] text-amber-600">Workload ↓</span>
                  <span className="text-xs font-semibold text-amber-900">
                    {wr === null ? '—' : `${Math.max(0, wr)}%`}
                  </span>
                </div>
              </div>
            )
          })()
        ) : (
          <p className="mt-1 text-xs text-gray-600">
            Threshold + validation workload controls.
          </p>
        )}
      </div>

      <div className="space-y-3">
        {typeof threshold === 'number' &&
        onThresholdChange &&
        !criterionMetrics?.length ? (
          <div className="flex items-center justify-between gap-3">
            <label className="text-sm text-gray-700">Threshold</label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={threshold}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                const v = Number(e.target.value)
                if (!Number.isFinite(v)) return
                onThresholdChange(Math.max(0, Math.min(1, v)))
              }}
              className="w-24 rounded-md border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        ) : null}

        {showFilter ? (
          <div className="flex items-center justify-between gap-3">
            <label className="text-sm text-gray-700">Filter</label>
            <select
              value={filterMode}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                onFilterModeChange(e.target.value as any)
              }
              className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm"
            >
              <option value="needs">Needs human review</option>
              <option value="unvalidated">Unvalidated</option>
              <option value="validated">Validated</option>
              <option value="not_screened">Not screened yet</option>
              <option value="all">All</option>
            </select>
          </div>
        ) : null}

        {summary ? (
          <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-gray-700">Progress</div>
              <div className="text-[11px] text-gray-600">
                Workload Reduction:{' '}
                <span className="font-medium">
                  {(() => {
                    // Only calculate workload reduction for citations that have been screened
                    const screened = total - notScreened
                    if (screened === 0 || total === 0) return '—'
                    // Workload reduction = % of screened citations that don't need human review
                    const reduction = Math.round(
                      (1 - queueTotal / screened) * 100,
                    )
                    return `${Math.max(0, Math.min(100, reduction))}%`
                  })()}
                </span>
              </div>
            </div>

            {/* Single overall progress bar (segments sum to 100%) */}
            <div className="mt-2">
              <div className="relative h-3 w-full overflow-hidden rounded bg-gray-200">
                {/* Validated (green) */}
                <div
                  className="absolute top-0 left-0 h-3 bg-emerald-600"
                  style={{
                    width: `${Math.min(100, Math.max(0, validatedPct))}%`,
                  }}
                />

                {/* Remaining human review queue (amber) */}
                <div
                  className="absolute top-0 h-3 bg-amber-400"
                  style={{
                    left: `${Math.min(100, Math.max(0, validatedPct))}%`,
                    width: `${Math.min(100, Math.max(0, queueRemainingPct))}%`,
                  }}
                />

                {/* Resolved (no human review needed) (gray) */}
                <div
                  className="absolute top-0 h-3 bg-gray-400"
                  style={{
                    left: `${Math.min(100, Math.max(0, validatedPct + queueRemainingPct))}%`,
                    width: `${Math.min(100, Math.max(0, resolvedPct))}%`,
                  }}
                  title="Resolved (not in queue)"
                />

                {/* Not screened yet (light gray) */}
                <div
                  className="absolute top-0 h-3 bg-gray-300"
                  style={{
                    left: `${Math.min(100, Math.max(0, validatedPct + queueRemainingPct + resolvedPct))}%`,
                    width: `${Math.min(100, Math.max(0, notScreenedPct))}%`,
                  }}
                />
              </div>
            </div>

            <div className="mt-2 grid grid-cols-1 gap-1 text-[11px] text-gray-600">
              <div>
                <span className="font-medium text-gray-700">Validated:</span>{' '}
                {validatedAll} / {total}
              </div>
              <div>
                <span className="font-medium text-gray-700">
                  Human review queue:
                </span>{' '}
                {queueRemaining} remaining (of {queueTotal})
              </div>
              {/* <div>
                <span className="font-medium text-gray-700">Resolved (no review needed):</span> {resolvedRemaining}
              </div> */}
              <div>
                <span className="font-medium text-gray-700">
                  Not screened yet:
                </span>{' '}
                {notScreened}
              </div>
            </div>
          </div>
        ) : null}

        {/* Removed page-local workload summary (we want SR-wide progress only). */}

        {criterionMetrics?.length ? (
          <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-gray-700">Criteria</div>
              {onSaveThresholds ? (
                <div className="flex items-center gap-2">
                  <div className="text-[11px] text-gray-600">
                    {thresholdsDirty ? 'Unsaved changes' : 'Up to date'}
                  </div>
                  <button
                    type="button"
                    onClick={onSaveThresholds}
                    disabled={!thresholdsDirty || savingThresholds}
                    className="rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
                  >
                    {savingThresholds ? 'Saving…' : 'Save thresholds'}
                  </button>
                </div>
              ) : null}
            </div>

            <div className="mt-2 space-y-2">
              {criterionMetrics.map((c) => {
                const thresholdPercent =
                  sliderPercents[c.criterion_key] ??
                  Math.round(Math.max(0, Math.min(1, c.threshold)) * 100)
                const cal = calibByKey.get(c.criterion_key)
                const rec =
                  cal && typeof cal.recommended_threshold === 'number'
                    ? Math.max(0, Math.min(1, cal.recommended_threshold))
                    : null
                const cm = c.confusion_matrix
                const npvPct =
                  typeof c.npv === 'number'
                    ? Math.round(c.npv * 100)
                    : cm && cm.fn === 0
                      ? 100
                      : null
                const updateThreshold = (percent: number) => {
                  const value = Math.max(0, Math.min(100, Math.round(percent)))
                  pendingSliderPercents.current[c.criterion_key] = value
                  setSliderPercents((previous) => ({
                    ...previous,
                    [c.criterion_key]: value,
                  }))
                  onCriterionThresholdChange?.(c.criterion_key, value / 100)
                }
                const commitThreshold = (percent: number) => {
                  const value = Math.max(0, Math.min(100, Math.round(percent)))
                  onCriterionThresholdCommit?.(c.criterion_key, value / 100)
                }

                return (
                  <div
                    key={c.criterion_key}
                    className="flex items-start gap-4 rounded border border-gray-100 bg-white p-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-gray-800">
                        {c.label}
                      </div>
                      <div className="mt-1 space-y-0.5 text-[11px] text-gray-500">
                        {npvPct !== null ? <div>NPV: {npvPct}%</div> : null}
                        {c.has_run_count > 0 ? (
                          <div>
                            Workload ↓:{' '}
                            {Math.max(
                              0,
                              Math.round(
                                (1 -
                                  c.needs_human_review_count /
                                    c.has_run_count) *
                                  100,
                              ),
                            )}
                            %
                          </div>
                        ) : null}
                      </div>
                    </div>

                    <div className="w-44 shrink-0">
                      <div className="mb-1 flex items-center gap-1 text-[10px] text-gray-500">
                        <span>Threshold</span>
                        <span className="font-medium text-gray-700">
                          {thresholdPercent}%
                        </span>
                      </div>
                      <div
                        className="relative cursor-pointer pt-7"
                        role="slider"
                        tabIndex={0}
                        aria-label={`Threshold for ${c.label}`}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={thresholdPercent}
                        onPointerDown={(e) => {
                          e.currentTarget.setPointerCapture(e.pointerId)
                          const bounds = e.currentTarget.getBoundingClientRect()
                          updateThreshold(
                            ((e.clientX - bounds.left) / bounds.width) * 100,
                          )
                        }}
                        onPointerMove={(e) => {
                          if (!e.currentTarget.hasPointerCapture(e.pointerId))
                            return
                          const bounds = e.currentTarget.getBoundingClientRect()
                          updateThreshold(
                            ((e.clientX - bounds.left) / bounds.width) * 100,
                          )
                        }}
                        onPointerUp={(e) => {
                          const bounds = e.currentTarget.getBoundingClientRect()
                          commitThreshold(
                            ((e.clientX - bounds.left) / bounds.width) * 100,
                          )
                          e.currentTarget.releasePointerCapture(e.pointerId)
                        }}
                        onKeyDown={(e) => {
                          let next: number | null = null
                          if (e.key === 'ArrowLeft' || e.key === 'ArrowDown')
                            next = thresholdPercent - 1
                          if (e.key === 'ArrowRight' || e.key === 'ArrowUp')
                            next = thresholdPercent + 1
                          if (e.key === 'Home') next = 0
                          if (e.key === 'End') next = 100
                          if (e.key === 'PageDown') next = thresholdPercent - 10
                          if (e.key === 'PageUp') next = thresholdPercent + 10
                          if (next === null) return
                          e.preventDefault()
                          updateThreshold(next)
                          commitThreshold(next)
                        }}
                      >
                        {rec !== null ? (
                          <div
                            className="pointer-events-none absolute top-0 bottom-0 z-10 w-px"
                            style={{ left: `${rec * 100}%` }}
                            aria-hidden="true"
                          >
                            <span className="absolute top-0 left-1/2 -translate-x-1/2 text-[9px] font-medium whitespace-nowrap text-amber-700">
                              Rec {Math.round(rec * 100)}%
                            </span>
                            <span className="absolute top-3 bottom-0 left-0 w-px bg-amber-500" />
                          </div>
                        ) : null}
                        <div className="relative h-1 w-full rounded-full bg-gray-300">
                          <div
                            className="absolute inset-y-0 left-0 rounded-full bg-blue-600"
                            style={{ width: `${thresholdPercent}%` }}
                          />
                          <div
                            className="absolute top-1/2 h-4 w-4 rounded-full bg-blue-600 shadow-sm"
                            style={{
                              left: `${thresholdPercent}%`,
                              transform: 'translate(-50%, -50%)',
                            }}
                          />
                        </div>
                      </div>
                      <div className="mt-0.5 flex justify-between text-[9px] text-gray-400">
                        <span>0%</span>
                        <span>100%</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
