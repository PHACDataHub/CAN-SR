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
  accuracy_critical_agent?: number | null
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
  onFilterModeChange: (v: 'needs' | 'validated' | 'unvalidated' | 'not_screened' | 'all') => void
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
  const [thresholdText, setThresholdText] = React.useState<Record<string, string>>({})

  // Kept for backwards-compatibility with callers that still compute page-local stats.
  void _stats

  const calibByKey = React.useMemo(() => {
    const m = new Map<string, CalibrationCriterion>()
    for (const c of calibration || []) m.set(c.criterion_key, c)
    return m
  }, [calibration])

  // Keep a stable text representation so users can type freely.
  React.useEffect(() => {
    if (!criterionMetrics?.length) return
    setThresholdText((prev) => {
      const next = { ...prev }
      for (const c of criterionMetrics) {
        const k = c.criterion_key
        if (!(k in next)) {
          next[k] = Number.isFinite(c.threshold) ? String(c.threshold) : '0.9'
        }
      }
      return next
    })
  }, [criterionMetrics])
  const total = summary?.total_citations ?? 0
  const validatedAll = summary?.validated_all ?? 0
  const notScreened = summary?.not_screened_yet ?? 0

  // Human review queue is a subset of unvalidated; "not screened yet" should not be part of the queue.
  const queueTotal = summary?.needs_review_total ?? 0
  const queueValidated = summary?.validated_needs_review ?? 0
  const queueRemaining = Math.max(0, queueTotal - queueValidated)

  const validatedPct = total > 0 ? (validatedAll / total) * 100 : 0
  const queuePct = total > 0 ? (queueTotal / total) * 100 : 0
  const notScreenedPct = total > 0 ? (notScreened / total) * 100 : 0

  const queueStartPct = Math.min(100, Math.max(0, validatedPct))

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
        <p className="mt-1 text-xs text-gray-600">
          Threshold + validation workload controls. (Accuracy/curves will be powered by Phase 2 metrics.)
        </p>
      </div>

      <div className="space-y-3">
        {typeof threshold === 'number' && onThresholdChange && !criterionMetrics?.length ? (
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
                  {total > 0 ? `${Math.round((1-(queueTotal / total)) * 100)}%` : '—'}
                </span>
              </div>
            </div>

            {/* Combined progress bar */}
            <div className="mt-2">
              <div className="relative h-3 w-full overflow-hidden rounded bg-gray-200">
                {/* Validated (green) */}
                <div
                  className="absolute left-0 top-0 h-3 bg-emerald-600"
                  style={{ width: `${Math.min(100, Math.max(0, validatedPct))}%` }}
                />

                {/* Needs human review queue (amber) as part of remainder */}
                <div
                  className="absolute top-0 h-3 bg-amber-400"
                  style={{
                    left: `${Math.min(100, Math.max(0, validatedPct))}%`,
                    width: `${Math.min(100, Math.max(0, queuePct))}%`,
                  }}
                />

                {/* Not screened yet (gray) */}
                <div
                  className="absolute top-0 h-3 bg-gray-400"
                  style={{
                    left: `${Math.min(100, Math.max(0, validatedPct + queuePct))}%`,
                    width: `${Math.min(100, Math.max(0, notScreenedPct))}%`,
                  }}
                />

                {/* Inner overlay: progress within queue (thin bar) */}
                {queueTotal > 0 ? (
                  <div
                    className="absolute top-0 h-1 bg-amber-700"
                    style={{
                      left: `${Math.min(100, Math.max(0, validatedPct))}%`,
                      width: `${Math.min(100, Math.max(0, (queueValidated / total) * 100))}%`,
                    }}
                  />
                ) : null}

                {/* Dotted marker: start of human review queue */}
                {total > 0 ? (
                  <div
                    className="absolute top-0 h-3 border-l border-dashed border-gray-900/40"
                    style={{ left: `${queueStartPct}%` }}
                    title="Human review queue starts here"
                  />
                ) : null}
              </div>
            </div>

            <div className="mt-2 grid grid-cols-1 gap-1 text-[11px] text-gray-600">
              <div>
                <span className="font-medium text-gray-700">Validated:</span> {validatedAll} / {total}
              </div>
              <div>
                <span className="font-medium text-gray-700">Human review queue:</span> {queueRemaining} remaining (of {queueTotal})
              </div>
              <div>
                <span className="font-medium text-gray-700">Not screened yet:</span> {notScreened}
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
                const acc = typeof c.accuracy === 'number' ? Math.round(c.accuracy * 100) : null
                const accCrit = typeof c.accuracy_critical_agent === 'number' ? Math.round(c.accuracy_critical_agent * 100) : null
                const textVal = thresholdText[c.criterion_key] ?? (Number.isFinite(c.threshold) ? String(c.threshold) : '0.9')
                const cal = calibByKey.get(c.criterion_key)
                const rec =
                  cal && typeof cal.recommended_threshold === 'number'
                    ? Math.round(cal.recommended_threshold * 100) / 100
                    : null

                const curve = Array.isArray(cal?.curve) ? cal!.curve : []
                const recPoint =
                  rec === null
                    ? null
                    : curve.find((p) => Math.abs(p.threshold - rec) < 1e-9) || null
                const wr =
                  typeof recPoint?.workload_reduction === 'number'
                    ? Math.round(recPoint.workload_reduction * 100)
                    : null
                const recall =
                  typeof recPoint?.recall === 'number' ? Math.round(recPoint.recall * 100) : null
                const fpr = typeof recPoint?.fpr === 'number' ? Math.round(recPoint.fpr * 100) : null

                return (
                  <details key={c.criterion_key} className="rounded border border-gray-100 bg-white p-2">
                    <summary className="cursor-pointer list-none">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-medium text-gray-800">{c.label}</div>
                          <div className="mt-1 space-y-0.5 text-[11px] text-gray-500">
                            <div>Accuracy: {acc === null ? '—' : `${acc}%`}</div>
                            {accCrit === null ? null : (
                              <div>Critical Agent Agreement: {accCrit}%</div>
                            )}
                            {cal ? <div>Validated: {cal.validated_n}</div> : null}
                            {rec === null ? null : <div>Recommended thr: {rec}</div>}
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          <label className="text-[11px] text-gray-600">Thr</label>
                          <input
                            type="text"
                            inputMode="decimal"
                            value={textVal}
                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                              const raw = e.target.value
                              setThresholdText((p) => ({ ...p, [c.criterion_key]: raw }))
                              const v = Number(raw)
                              if (!Number.isFinite(v)) return
                              onCriterionThresholdChange?.(c.criterion_key, Math.max(0, Math.min(1, v)))
                            }}
                            onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                              if (e.key !== 'Enter') return
                              const v = Number((e.currentTarget as HTMLInputElement).value)
                              if (!Number.isFinite(v)) return
                              onCriterionThresholdCommit?.(c.criterion_key, Math.max(0, Math.min(1, v)))
                            }}
                            className="w-20 rounded-md border border-gray-200 px-2 py-1 text-xs"
                          />
                          <span className="text-[11px] text-gray-400">▾</span>
                        </div>
                      </div>
                    </summary>

                    <div className="mt-2 space-y-2 text-[11px] text-gray-700">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="rounded border border-gray-100 bg-gray-50 p-2">
                          Low confidence: {c.low_confidence_count}
                        </div>
                        <div className="rounded border border-gray-100 bg-gray-50 p-2">
                          Critical disagreements: {c.critical_disagreement_count}
                        </div>
                      </div>

                      {cal ? (
                        <div className="rounded border border-gray-100 bg-gray-50 p-2">
                          <div className="text-[11px] font-medium text-gray-700">Calibration (validated set)</div>
                          <div className="mt-1 grid grid-cols-2 gap-2">
                            <div className="rounded border border-gray-100 bg-white p-2">
                              Recommended thr: {rec === null ? '—' : rec}
                            </div>
                            <div className="rounded border border-gray-100 bg-white p-2">
                              Validated n: {cal.validated_n}
                            </div>
                            <div className="rounded border border-gray-100 bg-white p-2">
                              Recall @ rec: {recall === null ? '—' : `${recall}%`}
                            </div>
                            <div className="rounded border border-gray-100 bg-white p-2">
                              FPR @ rec: {fpr === null ? '—' : `${fpr}%`}
                            </div>
                            <div className="col-span-2 rounded border border-gray-100 bg-white p-2">
                              Workload ↓ @ rec: {wr === null ? '—' : `${wr}%`}
                            </div>
                          </div>
                          {cal.recommended_reason ? (
                            <div className="mt-2 text-[11px] text-gray-500">
                              {cal.recommended_reason}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </details>
                )
              })}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
