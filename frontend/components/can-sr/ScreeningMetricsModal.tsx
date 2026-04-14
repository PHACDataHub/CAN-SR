'use client'

import React from 'react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type {
  CalibrationCriterion,
  ScreeningCriterionMetrics,
  ScreeningMetricsSummary,
} from '@/components/can-sr/ScreeningMetricsPanel'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title?: string
  stepLabel?: string
  summary?: ScreeningMetricsSummary
  criterionMetrics?: ScreeningCriterionMetrics[]
  calibration?: CalibrationCriterion[]
  srId?: string | null
  step?: 'l1' | 'l2' | string
}

function pct(n: number | null | undefined, d: number | null | undefined): number | null {
  const nn = typeof n === 'number' ? n : null
  const dd = typeof d === 'number' ? d : null
  if (nn === null || dd === null || dd <= 0) return null
  return (nn / dd) * 100
}

function sparkline(values: number[], width = 140, height = 34): string {
  if (!values.length) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const dx = width / Math.max(1, values.length - 1)
  return values
    .map((v, i) => {
      const x = i * dx
      const y = height - ((v - min) / span) * height
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}

export default function ScreeningMetricsModal({
  open,
  onOpenChange,
  title = 'Screening metrics',
  stepLabel,
  summary,
  criterionMetrics,
  calibration,
  srId,
  step,
}: Props) {
  const calibByKey = React.useMemo(() => {
    const m = new Map<string, CalibrationCriterion>()
    for (const c of calibration || []) m.set(c.criterion_key, c)
    return m
  }, [calibration])

  const total = summary?.total_citations ?? 0
  const validatedAll = summary?.validated_all ?? 0
  const needsReview = summary?.needs_review_total ?? 0
  const notScreened = summary?.not_screened_yet ?? 0

  const validatedPct = pct(validatedAll, total)
  const queuePct = pct(needsReview, total)
  const notScreenedPct = pct(notScreened, total)

  // --- Critical prompt additions editor (Phase 3+)
  const stepNorm = (step || '').toLowerCase() as any
  const [criticalAdditions, setCriticalAdditions] = React.useState<Record<string, any> | null>(null)
  const [loadingCPA, setLoadingCPA] = React.useState(false)
  const [savingCPA, setSavingCPA] = React.useState(false)

  React.useEffect(() => {
    if (!open) return
    if (!srId) return
    if (!(stepNorm === 'l1' || stepNorm === 'l2')) return

    const load = async () => {
      setLoadingCPA(true)
      try {
        const res = await fetch(
          `/api/can-sr/reviews/critical-prompt-additions?sr_id=${encodeURIComponent(String(srId))}`,
          { method: 'GET' },
        )
        const j = await res.json().catch(() => ({}))
        const cpa = res.ok ? j?.critical_prompt_additions : null
        setCriticalAdditions(typeof cpa === 'object' && cpa ? cpa : { l1: {}, l2: {} })
      } catch {
        setCriticalAdditions({ l1: {}, l2: {} })
      } finally {
        setLoadingCPA(false)
      }
    }
    load()
  }, [open, srId, stepNorm])

  const updateAddition = (criterionKey: string, value: string) => {
    setCriticalAdditions((prev) => {
      const base = prev && typeof prev === 'object' ? prev : { l1: {}, l2: {} }
      const block = (base as any)[stepNorm] && typeof (base as any)[stepNorm] === 'object' ? (base as any)[stepNorm] : {}
      return {
        ...(base as any),
        [stepNorm]: {
          ...block,
          [criterionKey]: value,
        },
      }
    })
  }

  const saveCPA = async () => {
    if (!srId) return
    if (!(stepNorm === 'l1' || stepNorm === 'l2')) return
    setSavingCPA(true)
    try {
      const payload = { critical_prompt_additions: criticalAdditions || { l1: {}, l2: {} } }
      const res = await fetch(
        `/api/can-sr/reviews/critical-prompt-additions?sr_id=${encodeURIComponent(String(srId))}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      const j = await res.json().catch(() => ({}))
      if (res.ok) {
        setCriticalAdditions(j?.critical_prompt_additions || payload.critical_prompt_additions)
      }
    } finally {
      setSavingCPA(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[920px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <div className="text-xs text-gray-600">
            {stepLabel ? `${stepLabel} · ` : ''}Operational + reporting view (validated-set calibration)
          </div>
        </DialogHeader>

        <div className="max-h-[70vh] overflow-auto">
          {/* Summary */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded border border-gray-100 bg-gray-50 p-3">
              <div className="text-[11px] text-gray-500">Validated</div>
              <div className="mt-1 text-sm font-semibold text-gray-900">
                {validatedAll} / {total}
              </div>
              <div className="mt-1 text-[11px] text-gray-600">
                {validatedPct === null ? '—' : `${validatedPct.toFixed(1)}%`}
              </div>
            </div>
            <div className="rounded border border-gray-100 bg-gray-50 p-3">
              <div className="text-[11px] text-gray-500">Human review queue</div>
              <div className="mt-1 text-sm font-semibold text-gray-900">{needsReview}</div>
              <div className="mt-1 text-[11px] text-gray-600">
                {queuePct === null ? '—' : `${queuePct.toFixed(1)}% of SR`}
              </div>
            </div>
            <div className="rounded border border-gray-100 bg-gray-50 p-3">
              <div className="text-[11px] text-gray-500">Not screened yet</div>
              <div className="mt-1 text-sm font-semibold text-gray-900">{notScreened}</div>
              <div className="mt-1 text-[11px] text-gray-600">
                {notScreenedPct === null ? '—' : `${notScreenedPct.toFixed(1)}% of SR`}
              </div>
            </div>
            <div className="rounded border border-gray-100 bg-gray-50 p-3">
              <div className="text-[11px] text-gray-500">Auto-excluded</div>
              <div className="mt-1 text-sm font-semibold text-gray-900">
                {summary?.auto_excluded ?? 0}
              </div>
              <div className="mt-1 text-[11px] text-gray-600">(confident exclude + critical agrees)</div>
            </div>
          </div>

          {/* Per-criterion */}
          <div className="mt-6">
            <div className="text-xs font-semibold text-gray-800">Per-criterion analytics</div>
            <div className="mt-2 space-y-3">
              {(criterionMetrics || []).map((m) => {
                const accPct = typeof m.accuracy === 'number' ? m.accuracy * 100 : null
                const cal = calibByKey.get(m.criterion_key)
                const rec =
                  cal && typeof cal.recommended_threshold === 'number'
                    ? cal.recommended_threshold
                    : null
                const curve = Array.isArray(cal?.curve) ? cal!.curve : []
                const recPoint =
                  rec === null
                    ? null
                    : curve.find((p) => Math.abs(p.threshold - rec) < 1e-9) || null
                const wr =
                  recPoint && typeof recPoint.workload_reduction === 'number'
                    ? recPoint.workload_reduction * 100
                    : null
                const recall =
                  recPoint && typeof recPoint.recall === 'number' ? recPoint.recall * 100 : null
                const fpr = recPoint && typeof recPoint.fpr === 'number' ? recPoint.fpr * 100 : null

                const hist = Array.isArray(cal?.histogram) ? cal!.histogram : []
                const disagreeShare = hist.map((b) => {
                  const t = (b.agree || 0) + (b.disagree || 0)
                  return t > 0 ? (b.disagree || 0) / t : 0
                })
                const points = sparkline(disagreeShare)

                return (
                  <div key={m.criterion_key} className="rounded border border-gray-100 bg-white p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-gray-900">{m.label}</div>
                        <div className="mt-1 text-[11px] text-gray-600">
                          Current threshold: <span className="font-medium">{m.threshold}</span>
                          {rec === null ? '' : ` · Recommended: ${rec.toFixed(2)}`}
                          {cal ? ` · Validated n=${cal.validated_n}` : ''}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-[11px] text-gray-500">Accuracy</div>
                        <div className="text-sm font-semibold text-gray-900">
                          {accPct === null ? '—' : `${accPct.toFixed(0)}%`}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Needs review (this criterion): {m.needs_human_review_count}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Confident exclude: {m.confident_exclude_count}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Low confidence: {m.low_confidence_count}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Critical disagreement: {m.critical_disagreement_count}
                      </div>
                    </div>

                    {(stepNorm === 'l1' || stepNorm === 'l2') ? (
                      <div className="mt-3 rounded border border-gray-100 bg-gray-50 p-2">
                        <div className="mb-1 text-[11px] font-medium text-gray-700">
                          Critical prompt additions (for this criterion)
                        </div>
                        <textarea
                          value={
                            String(
                              (criticalAdditions as any)?.[stepNorm]?.[m.criterion_key] || '',
                            )
                          }
                          onChange={(e) => updateAddition(m.criterion_key, e.target.value)}
                          rows={3}
                          className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-[11px]"
                          placeholder="Add SR-specific instructions that will be injected into the CRITICAL prompt for this criterion."
                        />
                      </div>
                    ) : null}

                    <div className="mt-3 grid grid-cols-3 gap-2">
                      <div className="rounded border border-gray-100 bg-gray-50 p-2 text-[11px]">
                        <div className="text-gray-500">Recall @ rec</div>
                        <div className="font-medium text-gray-900">
                          {recall === null ? '—' : `${recall.toFixed(0)}%`}
                        </div>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2 text-[11px]">
                        <div className="text-gray-500">FPR @ rec</div>
                        <div className="font-medium text-gray-900">
                          {fpr === null ? '—' : `${fpr.toFixed(0)}%`}
                        </div>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2 text-[11px]">
                        <div className="text-gray-500">Workload ↓ @ rec</div>
                        <div className="font-medium text-gray-900">
                          {wr === null ? '—' : `${wr.toFixed(0)}%`}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="text-[11px] text-gray-500">
                        Disagreement share by confidence bin
                      </div>
                      <svg width={140} height={34} className="shrink-0">
                        <polyline
                          fill="none"
                          stroke="rgb(244 63 94)"
                          strokeWidth="2"
                          points={points}
                        />
                      </svg>
                    </div>
                  </div>
                )
              })}
            </div>

            {(stepNorm === 'l1' || stepNorm === 'l2') ? (
              <div className="mt-4 flex items-center justify-between gap-3 rounded border border-gray-100 bg-white p-3">
                <div className="text-xs text-gray-600">
                  {loadingCPA ? 'Loading critical prompt additions…' : 'Edit additions above, then save.'}
                </div>
                <button
                  onClick={saveCPA}
                  disabled={savingCPA || loadingCPA || !srId}
                  className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                >
                  {savingCPA ? 'Saving…' : 'Save critical additions'}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
