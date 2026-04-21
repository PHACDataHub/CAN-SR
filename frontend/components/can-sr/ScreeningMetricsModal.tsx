'use client'

import React from 'react'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type {
  CalibrationCriterion,
  LiveConfidenceHistogramCriterion,
  ScreeningCriterionMetrics,
  ScreeningMetricsSummary,
} from '@/components/can-sr/ScreeningMetricsPanel'
import { getAuthToken, getTokenType } from '@/lib/auth'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title?: string
  stepLabel?: string
  summary?: ScreeningMetricsSummary
  criterionMetrics?: ScreeningCriterionMetrics[]
  calibration?: CalibrationCriterion[]
  liveHistogram?: LiveConfidenceHistogramCriterion[]
  srId?: string | null
  step?: 'l1' | 'l2' | string
}

function pct(
  n: number | null | undefined,
  d: number | null | undefined,
): number | null {
  const nn = typeof n === 'number' ? n : null
  const dd = typeof d === 'number' ? d : null
  if (nn === null || dd === null || dd <= 0) return null
  return (nn / dd) * 100
}

type HistogramBin = {
  bin_start: number
  bin_end: number
  unlabelled: number
  agree: number
  disagree: number
}

type ThresholdMarkers = { current?: number | null; recommended?: number | null }

function markerList(markers?: ThresholdMarkers) {
  const markerPositions: {
    kind: 'current' | 'recommended'
    xPct: number
    label: string
  }[] = []
  const cur =
    typeof markers?.current === 'number' ? clamp01(markers!.current) : null
  const rec =
    typeof markers?.recommended === 'number'
      ? clamp01(markers!.recommended)
      : null
  if (cur !== null) {
    markerPositions.push({
      kind: 'current',
      xPct: cur * 100,
      label: `Current thr ${Math.round(cur * 100)}% (${cur.toFixed(2)})`,
    })
  }
  if (rec !== null) {
    markerPositions.push({
      kind: 'recommended',
      xPct: rec * 100,
      label: `Recommended thr ${Math.round(rec * 100)}% (${rec.toFixed(2)})`,
    })
  }
  return { markerPositions, cur, rec }
}

function renderStackedHistogramSvg(
  bins: HistogramBin[],
  markers?: ThresholdMarkers,
) {
  const safeBins = Array.isArray(bins) ? bins : []
  const totals = safeBins.map(
    (b) => (b.unlabelled || 0) + (b.agree || 0) + (b.disagree || 0),
  )
  const max = Math.max(1, ...totals)

  const { markerPositions, cur, rec } = markerList(markers)

  const viewW = 100
  const viewH = 52
  const topPad = 2
  const chartH = 44

  return (
    <div className="mt-2">
      <div className="text-[11px] text-gray-500">
        Confidence distribution (live)
      </div>
      <div className="mt-1">
        <svg
          viewBox={`0 0 ${viewW} ${viewH}`}
          width="100%"
          height={viewH}
          preserveAspectRatio="none"
        >
          {/* bars */}
          {safeBins.map((b, i) => {
            const start = clamp01(Number(b.bin_start))
            const end = clamp01(Number(b.bin_end))
            const x0 = start * 100
            const x1 = end * 100
            const w = Math.max(0, x1 - x0)

            const unlabelled = b.unlabelled || 0
            const agree = b.agree || 0
            const disagree = b.disagree || 0
            const total = unlabelled + agree + disagree
            const h = total > 0 ? (total / max) * chartH : 0

            const uh = total > 0 ? (h * unlabelled) / total : 0
            const gh = total > 0 ? (h * agree) / total : 0
            const rh = Math.max(0, h - uh - gh)

            const yBottom = topPad + chartH
            const yRed = yBottom - rh
            const yGreen = yRed - gh
            const yBlue = yGreen - uh

            const title = `${start.toFixed(2)}–${end.toFixed(2)}: total ${total} (unlabelled ${unlabelled}, agree ${agree}, disagree ${disagree})`

            return (
              <g key={i}>
                <title>{title}</title>
                {/* disagree (red) */}
                {rh > 0 ? (
                  <rect
                    x={x0}
                    y={yRed}
                    width={w}
                    height={rh}
                    fill="rgb(251 113 133)"
                  />
                ) : null}
                {/* agree (green) */}
                {gh > 0 ? (
                  <rect
                    x={x0}
                    y={yGreen}
                    width={w}
                    height={gh}
                    fill="rgb(16 185 129)"
                  />
                ) : null}
                {/* unlabelled (blue) */}
                {uh > 0 ? (
                  <rect
                    x={x0}
                    y={yBlue}
                    width={w}
                    height={uh}
                    fill="rgb(59 130 246)"
                  />
                ) : null}
              </g>
            )
          })}

          {/* marker lines */}
          {markerPositions.map((m) => {
            const x = (m.xPct / 100) * viewW
            return (
              <g key={m.kind}>
                <title>{m.label}</title>
                {m.kind === 'current' ? (
                  <line
                    x1={x}
                    x2={x}
                    y1={topPad}
                    y2={topPad + chartH}
                    stroke="rgba(55,65,81,0.85)"
                    strokeWidth={0.6}
                  />
                ) : (
                  <line
                    x1={x}
                    x2={x}
                    y1={topPad}
                    y2={topPad + chartH}
                    stroke="rgba(37,99,235,0.85)"
                    strokeWidth={0.6}
                    strokeDasharray="2,2"
                  />
                )}
              </g>
            )
          })}

          {/* axis baseline */}
          <line
            x1={0}
            x2={viewW}
            y1={topPad + chartH}
            y2={topPad + chartH}
            stroke="rgba(229,231,235,1)"
            strokeWidth={0.6}
          />
        </svg>
      </div>

      <div className="mt-1 flex items-center justify-between text-[10px] text-gray-400">
        <span>0.0</span>
        <span>1.0</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-3 text-[10px] text-gray-500">
        <div className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-blue-500" />
          Unlabelled
        </div>
        <div className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500" />
          Agree
        </div>
        <div className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-rose-400" />
          Disagree
        </div>
        {cur !== null ? (
          <div className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm bg-gray-700/70" />
            Current ({Math.round(cur * 100)}%)
          </div>
        ) : null}
        {rec !== null ? (
          <div className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm border border-dashed border-blue-600/70" />
            Recommended ({Math.round(rec * 100)}%)
          </div>
        ) : null}
      </div>
    </div>
  )
}

function renderDisagreementShareChart(
  bins: {
    bin_start: number
    bin_end: number
    agree?: number
    disagree?: number
    unlabelled?: number
  }[],
  markers?: ThresholdMarkers,
) {
  const safeBins = Array.isArray(bins) ? bins : []
  const { markerPositions } = markerList(markers)

  // Fixed y scale: 0..1 (0..100%)
  const viewW = 100
  const viewH = 38
  const topPad = 2
  const chartH = 30

  const points: string[] = []
  for (const b of safeBins) {
    const start = clamp01(Number(b.bin_start))
    const end = clamp01(Number(b.bin_end))
    const mid = (start + end) / 2
    const agree = Number(b.agree || 0)
    const disagree = Number(b.disagree || 0)
    const labelled = agree + disagree
    if (labelled <= 0) continue
    const share = disagree / labelled
    const x = (mid * viewW).toFixed(4)
    const y = (topPad + (1 - clamp01(share)) * chartH).toFixed(4)
    points.push(`${x},${y}`)
  }

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] text-gray-500">
          Disagreement share by confidence bin
        </div>
        <div className="text-[10px] text-gray-400">0–100%</div>
      </div>
      <div className="mt-1">
        <svg
          viewBox={`0 0 ${viewW} ${viewH}`}
          width="100%"
          height={viewH}
          preserveAspectRatio="none"
        >
          {/* y grid */}
          <line
            x1={0}
            x2={viewW}
            y1={topPad}
            y2={topPad}
            stroke="rgba(229,231,235,1)"
            strokeWidth={0.6}
          />
          <line
            x1={0}
            x2={viewW}
            y1={topPad + chartH}
            y2={topPad + chartH}
            stroke="rgba(229,231,235,1)"
            strokeWidth={0.6}
          />
          {/* marker lines */}
          {markerPositions.map((m) => {
            const x = (m.xPct / 100) * viewW
            return m.kind === 'current' ? (
              <line
                key={m.kind}
                x1={x}
                x2={x}
                y1={topPad}
                y2={topPad + chartH}
                stroke="rgba(55,65,81,0.6)"
                strokeWidth={0.6}
              />
            ) : (
              <line
                key={m.kind}
                x1={x}
                x2={x}
                y1={topPad}
                y2={topPad + chartH}
                stroke="rgba(37,99,235,0.65)"
                strokeWidth={0.6}
                strokeDasharray="2,2"
              />
            )
          })}

          {/* series */}
          {points.length ? (
            <polyline
              fill="none"
              stroke="rgb(244 63 94)"
              strokeWidth="1.6"
              points={points.join(' ')}
            />
          ) : null}
        </svg>
      </div>
    </div>
  )
}

function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0
  return Math.max(0, Math.min(1, v))
}

function renderLiveConfidenceHistogram(
  hist: {
    bin_start: number
    bin_end: number
    unlabelled: number
    agree: number
    disagree: number
  }[],
  markers?: { current?: number | null; recommended?: number | null },
) {
  const bins = Array.isArray(hist) ? (hist as HistogramBin[]) : []
  return renderStackedHistogramSvg(bins, markers)
}

function renderConfidenceHistogram(
  hist: {
    bin_start: number
    bin_end: number
    agree: number
    disagree: number
  }[],
) {
  const bins = Array.isArray(hist) ? hist : []
  const totals = bins.map((b) => (b.agree || 0) + (b.disagree || 0))
  const max = Math.max(1, ...totals)
  return (
    <div className="mt-2">
      <div className="text-[11px] text-gray-500">
        Confidence distribution (validated set)
      </div>
      <div className="mt-1 flex items-end gap-1">
        {bins.map((b, i) => {
          const total = (b.agree || 0) + (b.disagree || 0)
          const agree = b.agree || 0
          const disagree = b.disagree || 0
          const h = Math.round((total / max) * 44)
          const agreePct = total > 0 ? agree / total : 0
          const start = clamp01(Number(b.bin_start))
          const end = clamp01(Number(b.bin_end))
          return (
            <div
              key={i}
              className="w-3"
              title={`${start.toFixed(2)}–${end.toFixed(2)}: total ${total} (agree ${agree}, disagree ${disagree})`}
            >
              <div
                className="w-3 rounded-sm bg-rose-400"
                style={{ height: `${h}px` }}
              >
                {/* overlay agree segment */}
                <div
                  className="w-3 rounded-sm bg-emerald-500"
                  style={{
                    height: `${Math.max(0, Math.round(h * agreePct))}px`,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex items-center justify-between text-[10px] text-gray-400">
        <span>0.0</span>
        <span>1.0</span>
      </div>
      <div className="mt-1 flex items-center gap-3 text-[10px] text-gray-500">
        <div className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500" />
          Agree
        </div>
        <div className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-rose-400" />
          Disagree
        </div>
      </div>
    </div>
  )
}

export default function ScreeningMetricsModal({
  open,
  onOpenChange,
  title = 'Screening metrics',
  stepLabel,
  summary,
  criterionMetrics,
  calibration,
  liveHistogram,
  srId,
  step,
}: Props) {
  const calibByKey = React.useMemo(() => {
    const m = new Map<string, CalibrationCriterion>()
    for (const c of calibration || []) m.set(c.criterion_key, c)
    return m
  }, [calibration])

  const liveByKey = React.useMemo(() => {
    const m = new Map<string, LiveConfidenceHistogramCriterion>()
    for (const c of liveHistogram || []) m.set(c.criterion_key, c)
    return m
  }, [liveHistogram])

  const total = summary?.total_citations ?? 0
  const validatedAll = summary?.validated_all ?? 0
  const queueTotal = summary?.needs_review_total ?? 0
  const queueValidated = summary?.validated_needs_review ?? 0
  const queueRemaining = Math.max(0, queueTotal - queueValidated)
  const notScreened = summary?.not_screened_yet ?? 0

  const validatedPct = pct(validatedAll, total)
  const queuePct = pct(queueTotal, total)
  const notScreenedPct = pct(notScreened, total)

  // --- Critical prompt additions editor (Phase 3+)
  const stepNorm = (step || '').toLowerCase() as any
  const [criticalAdditions, setCriticalAdditions] = React.useState<Record<
    string,
    any
  > | null>(null)
  const [loadingCPA, setLoadingCPA] = React.useState(false)
  const [savingCPA, setSavingCPA] = React.useState(false)

  React.useEffect(() => {
    if (!open) return
    if (!srId) return
    if (!(stepNorm === 'l1' || stepNorm === 'l2')) return

    const load = async () => {
      setLoadingCPA(true)
      try {
        const token = getAuthToken()
        const tokenType = getTokenType()
        const res = await fetch(
          `/api/can-sr/reviews/critical-prompt-additions?sr_id=${encodeURIComponent(String(srId))}`,
          {
            method: 'GET',
            headers: token
              ? { Authorization: `${tokenType} ${token}` }
              : undefined,
          },
        )
        const j = await res.json().catch(() => ({}))
        const cpa = res.ok ? j?.critical_prompt_additions : null
        setCriticalAdditions(
          typeof cpa === 'object' && cpa ? cpa : { l1: {}, l2: {} },
        )
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
      const block =
        (base as any)[stepNorm] && typeof (base as any)[stepNorm] === 'object'
          ? (base as any)[stepNorm]
          : {}
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
      const token = getAuthToken()
      const tokenType = getTokenType()
      const payload = {
        critical_prompt_additions: criticalAdditions || { l1: {}, l2: {} },
      }
      const res = await fetch(
        `/api/can-sr/reviews/critical-prompt-additions?sr_id=${encodeURIComponent(String(srId))}`,
        {
          method: 'PUT',
          headers: {
            ...(token ? { Authorization: `${tokenType} ${token}` } : {}),
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      )
      const j = await res.json().catch(() => ({}))
      if (res.ok) {
        setCriticalAdditions(
          j?.critical_prompt_additions || payload.critical_prompt_additions,
        )
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
            {stepLabel ? `${stepLabel} · ` : ''}Operational + reporting view
            (validated-set calibration)
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
              <div className="text-[11px] text-gray-500">
                Needs human review (unvalidated)
              </div>
              <div className="mt-1 text-sm font-semibold text-gray-900">
                {queueRemaining} remaining
              </div>
              <div className="mt-1 text-[11px] text-gray-600">
                Total flagged: {queueTotal} (validated: {queueValidated})
              </div>
              <div className="mt-1 text-[11px] text-gray-600">
                {queuePct === null ? '—' : `${queuePct.toFixed(1)}% of SR`}
              </div>
            </div>
            <div className="rounded border border-gray-100 bg-gray-50 p-3">
              <div className="text-[11px] text-gray-500">Not screened yet</div>
              <div className="mt-1 text-sm font-semibold text-gray-900">
                {notScreened}
              </div>
              <div className="mt-1 text-[11px] text-gray-600">
                {notScreenedPct === null
                  ? '—'
                  : `${notScreenedPct.toFixed(1)}% of SR`}
              </div>
            </div>
            <div className="rounded border border-gray-100 bg-gray-50 p-3">
              <div className="text-[11px] text-gray-500">Auto-excluded</div>
              <div className="mt-1 text-sm font-semibold text-gray-900">
                {summary?.auto_excluded ?? 0}
              </div>
              <div className="mt-1 text-[11px] text-gray-600">
                (confident exclude + critical agrees)
              </div>
            </div>
          </div>

          {/* Per-criterion */}
          <div className="mt-6">
            <div className="text-xs font-semibold text-gray-800">
              Per-criterion analytics
            </div>
            <div className="mt-2 space-y-3">
              {(criterionMetrics || []).map((m) => {
                const accPct =
                  typeof m.accuracy === 'number' ? m.accuracy * 100 : null
                const accAllPct =
                  typeof (m as any).accuracy_all === 'number'
                    ? (m as any).accuracy_all * 100
                    : null
                const accCritPct =
                  typeof (m as any).accuracy_critical_agent === 'number'
                    ? (m as any).accuracy_critical_agent * 100
                    : null
                const cal = calibByKey.get(m.criterion_key)
                const rec =
                  cal && typeof cal.recommended_threshold === 'number'
                    ? cal.recommended_threshold
                    : null
                const curve = Array.isArray(cal?.curve) ? cal!.curve : []
                const recPoint =
                  rec === null
                    ? null
                    : curve.find((p) => Math.abs(p.threshold - rec) < 1e-9) ||
                      null
                const wr =
                  recPoint && typeof recPoint.workload_reduction === 'number'
                    ? recPoint.workload_reduction * 100
                    : null
                const recall =
                  recPoint && typeof recPoint.recall === 'number'
                    ? recPoint.recall * 100
                    : null
                const fpr =
                  recPoint && typeof recPoint.fpr === 'number'
                    ? recPoint.fpr * 100
                    : null

                const hist = Array.isArray(cal?.histogram) ? cal!.histogram : []
                const live = liveByKey.get(m.criterion_key)

                return (
                  <div
                    key={m.criterion_key}
                    className="rounded border border-gray-100 bg-white p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-gray-900">
                          {m.label}
                        </div>
                        <div className="mt-1 text-[11px] text-gray-600">
                          Current threshold:{' '}
                          <span className="font-medium">{m.threshold}</span>
                          {rec === null
                            ? ''
                            : ` · Recommended: ${rec.toFixed(2)}`}
                          {cal ? ` · Validated n=${cal.validated_n}` : ''}
                        </div>
                      </div>
                      <div className="text-right">
                        {/* <div className="text-[11px] text-gray-500">
                          Accuracy (validated)
                        </div>
                        <div className="text-sm font-semibold text-gray-900">
                          {accPct === null ? '—' : `${accPct.toFixed(0)}%`}
                        </div> */}
                        <div className="mt-1 text-[11px] text-gray-500">
                          Accuracy
                        </div>
                        <div className="text-sm font-semibold text-gray-900">
                          {accAllPct === null ? '—' : `${accAllPct.toFixed(0)}%`}
                        </div>
                        <div className="mt-1 text-[11px] text-gray-500">
                          Critical Agent Agreement
                        </div>
                        <div className="text-sm font-semibold text-gray-900">
                          {accCritPct === null
                            ? '—'
                            : `${accCritPct.toFixed(0)}%`}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Low confidence: {m.low_confidence_count}
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Critical disagreements: {m.critical_disagreement_count}
                      </div>
                    </div>

                    {stepNorm === 'l1' || stepNorm === 'l2' ? (
                      <div className="mt-3 rounded border border-gray-100 bg-gray-50 p-2">
                        <div className="mb-1 text-[11px] font-medium text-gray-700">
                          Critical prompt additions (for this criterion)
                        </div>
                        <textarea
                          value={String(
                            (criticalAdditions as any)?.[stepNorm]?.[
                              m.criterion_key
                            ] || '',
                          )}
                          onChange={(e) =>
                            updateAddition(m.criterion_key, e.target.value)
                          }
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

                    {Array.isArray(live?.histogram) && live!.histogram.length
                      ? renderDisagreementShareChart(live!.histogram, {
                          current: m.threshold,
                          recommended: rec,
                        })
                      : hist.length
                        ? renderDisagreementShareChart(hist as any, {
                            current: m.threshold,
                            recommended: rec,
                          })
                        : null}

                    {/* Live (unlabelled/agree/disagree) distribution with threshold markers */}
                    {Array.isArray(live?.histogram) && live!.histogram.length
                      ? renderLiveConfidenceHistogram(live!.histogram, {
                          current: m.threshold,
                          recommended: rec,
                        })
                      : null}

                    {/* Keep validated-set histogram as a fallback when live is unavailable */}
                    {!live?.histogram?.length && hist.length
                      ? renderConfidenceHistogram(hist)
                      : null}
                  </div>
                )
              })}
            </div>

            {stepNorm === 'l1' || stepNorm === 'l2' ? (
              <div className="mt-4 flex items-center justify-between gap-3 rounded border border-gray-100 bg-white p-3">
                <div className="text-xs text-gray-600">
                  {loadingCPA
                    ? 'Loading critical prompt additions…'
                    : 'Edit additions above, then save.'}
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
