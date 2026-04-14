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

  filterMode: 'needs' | 'validated' | 'unvalidated' | 'all'
  onFilterModeChange: (v: 'needs' | 'validated' | 'unvalidated' | 'all') => void
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
  filterMode,
  onFilterModeChange,
  stats,
}: ScreeningMetricsPanelProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
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
            <option value="all">All</option>
          </select>
        </div>

        {summary ? (
          <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs font-medium text-gray-700">Validation summary</div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-700">
              <div className="rounded border border-gray-100 bg-white p-2">
                <div className="text-[11px] text-gray-500">All citations</div>
                <div className="font-semibold">
                  {summary.validated_all} / {summary.total_citations}
                </div>
              </div>
              <div className="rounded border border-gray-100 bg-white p-2">
                <div className="text-[11px] text-gray-500">Needs human review</div>
                <div className="font-semibold">
                  {summary.validated_needs_review} / {summary.needs_review_total}
                </div>
              </div>
            </div>
            <div className="mt-2 text-[11px] text-gray-500">
              Unvalidated: {summary.unvalidated_all} (all), {summary.unvalidated_needs_review} (needs review)
            </div>
          </div>
        ) : null}

        <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
          <div className="text-xs font-medium text-gray-700">
            Workload summary{stats?.scopeLabel ? ` (${stats.scopeLabel})` : ''}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-700">
            <div className="rounded border border-gray-100 bg-white p-2">
              <div className="text-[11px] text-gray-500">Total</div>
              <div className="font-semibold">{stats ? stats.total : '—'}</div>
            </div>
            <div className="rounded border border-gray-100 bg-white p-2">
              <div className="text-[11px] text-gray-500">Needs validation</div>
              <div className="font-semibold">{stats ? stats.needsValidation : '—'}</div>
            </div>
            <div className="rounded border border-gray-100 bg-white p-2">
              <div className="text-[11px] text-gray-500">Validated</div>
              <div className="font-semibold">{stats ? stats.validated : '—'}</div>
            </div>
            <div className="rounded border border-gray-100 bg-white p-2">
              <div className="text-[11px] text-gray-500">Unvalidated</div>
              <div className="font-semibold">{stats ? stats.unvalidated : '—'}</div>
            </div>
          </div>
        </div>

        {criterionMetrics?.length ? (
          <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs font-medium text-gray-700">Criteria thresholds & metrics</div>
            <div className="mt-2 space-y-2">
              {criterionMetrics.map((c) => (
                <div key={c.criterion_key} className="rounded border border-gray-100 bg-white p-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium text-gray-800 truncate">{c.label}</div>
                      <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-[11px] text-gray-600">
                        <div>Low conf: {c.low_confidence_count}</div>
                        <div>Critical disagree: {c.critical_disagreement_count}</div>
                        <div>Confident exclude: {c.confident_exclude_count}</div>
                        <div>Has run: {c.has_run_count}/{c.total_citations}</div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <label className="text-[11px] text-gray-600">Thr</label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={Number.isFinite(c.threshold) ? c.threshold : 0.9}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          const v = Number(e.target.value)
                          if (!Number.isFinite(v)) return
                          onCriterionThresholdChange?.(
                            c.criterion_key,
                            Math.max(0, Math.min(1, v)),
                          )
                        }}
                        className="w-20 rounded-md border border-gray-200 px-2 py-1 text-sm"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="rounded-md border border-gray-100 bg-gray-50 p-3 text-xs text-gray-700">
          <div className="font-medium">Performance (validated set)</div>
          <div className="mt-1 text-gray-500">
            Coming in Phase 2: agreement/accuracy, recommended thresholds, workload reduction curves.
          </div>
        </div>
      </div>
    </div>
  )
}
