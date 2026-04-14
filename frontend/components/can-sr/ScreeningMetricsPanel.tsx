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
  filterMode,
  onFilterModeChange,
  stats,
}: ScreeningMetricsPanelProps) {
  const [thresholdText, setThresholdText] = React.useState<Record<string, string>>({})

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

        {summary ? (
          <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs font-medium text-gray-700">Progress</div>

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
            <div className="text-xs font-medium text-gray-700">Criteria thresholds</div>

            <div className="mt-2 space-y-2">
              {criterionMetrics.map((c) => {
                const acc = typeof c.accuracy === 'number' ? Math.round(c.accuracy * 100) : null
                const textVal = thresholdText[c.criterion_key] ?? (Number.isFinite(c.threshold) ? String(c.threshold) : '0.9')
                return (
                  <details key={c.criterion_key} className="rounded border border-gray-100 bg-white p-2">
                    <summary className="cursor-pointer list-none">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-medium text-gray-800">{c.label}</div>
                          <div className="mt-1 text-[11px] text-gray-500">
                            Accuracy: {acc === null ? '—' : `${acc}%`}
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

                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-gray-700">
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Low confidence: {c.low_confidence_count}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Disagreement / missing critical: {c.critical_disagreement_count}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Confident exclude: {c.confident_exclude_count}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Has run: {c.has_run_count}/{c.total_citations}
                      </div>
                      <div className="col-span-2 rounded border border-gray-100 bg-gray-50 p-2">
                        Triggered review (this criterion): {c.needs_human_review_count}
                      </div>
                    </div>
                  </details>
                )
              })}
            </div>
          </div>
        ) : null}

        {calibration?.length ? (
          <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs font-medium text-gray-700">Calibration (validated set)</div>
            <div className="mt-2 space-y-2">
              {calibration.map((c) => {
                const rec =
                  typeof c.recommended_threshold === 'number'
                    ? Math.round(c.recommended_threshold * 100) / 100
                    : null
                const best = Array.isArray(c.curve)
                  ? c.curve.find(
                      (p) =>
                        typeof c.recommended_threshold === 'number' &&
                        Math.abs(p.threshold - c.recommended_threshold) < 1e-9,
                    )
                  : undefined

                const wr =
                  typeof best?.workload_reduction === 'number'
                    ? Math.round(best.workload_reduction * 100)
                    : null
                const recall =
                  typeof best?.recall === 'number' ? Math.round(best.recall * 100) : null
                const fpr = typeof best?.fpr === 'number' ? Math.round(best.fpr * 100) : null

                return (
                  <details key={c.criterion_key} className="rounded border border-gray-100 bg-white p-2">
                    <summary className="cursor-pointer list-none">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-medium text-gray-800">{c.label}</div>
                          <div className="mt-1 text-[11px] text-gray-500">
                            Validated: {c.validated_n}
                            {rec === null ? '' : ` · Recommended thr: ${rec}`}
                          </div>
                        </div>
                        <span className="text-[11px] text-gray-400">▾</span>
                      </div>
                    </summary>

                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-gray-700">
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Recall: {recall === null ? '—' : `${recall}%`}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        FPR: {fpr === null ? '—' : `${fpr}%`}
                      </div>
                      <div className="col-span-2 rounded border border-gray-100 bg-gray-50 p-2">
                        Workload reduction: {wr === null ? '—' : `${wr}%`}
                      </div>
                      {c.recommended_reason ? (
                        <div className="col-span-2 text-[11px] text-gray-500">
                          {c.recommended_reason}
                        </div>
                      ) : null}
                    </div>
                  </details>
                )
              })}
            </div>
          </div>
        ) : (
          <div className="rounded-md border border-gray-100 bg-gray-50 p-3 text-xs text-gray-700">
            <div className="font-medium">Calibration (validated set)</div>
            <div className="mt-1 text-gray-500">
              No calibration data yet. Validate citations to accumulate a comparison set.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
