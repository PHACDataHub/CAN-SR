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

function toLogScaleY(v: number, max: number): number {
  // Log scale for Y axis (counts). Maps [0, max] -> [0, 1] using log.
  if (v <= 0 || max <= 0) return 0
  return Math.log10(1 + v) / Math.log10(1 + max)
}

function renderStackedHistogramSvg(
  bins: HistogramBin[],
  markers?: ThresholdMarkers,
  useLogScale = false,
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

  // X axis is always linear (confidence 0-1); log scale only applies to Y axis
  const transformX = (v: number) => v * 100

  return (
    <div className="mt-2">
      <div className="text-[11px] text-gray-500">
        Confidence distribution (live) {useLogScale ? '· log scale' : ''}
      </div>
      <div className="mt-1">
        <svg
          viewBox={`0 0 ${viewW} ${viewH}`}
          width="100%"
          height={viewH}
          preserveAspectRatio="none"
        >
          {safeBins.map((b, i) => {
            const start = clamp01(Number(b.bin_start))
            const end = clamp01(Number(b.bin_end))
            const x0 = transformX(start)
            const x1 = transformX(end)
            const w = Math.max(0, x1 - x0)

            const unlabelled = b.unlabelled || 0
            const agree = b.agree || 0
            const disagree = b.disagree || 0
            const total = unlabelled + agree + disagree
            const hRaw = total > 0 ? total / max : 0
            const h = (useLogScale ? toLogScaleY(total, max) : hRaw) * chartH

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
                {rh > 0 ? (
                  <rect x={x0} y={yRed} width={w} height={rh} fill="rgb(251 113 133)" />
                ) : null}
                {gh > 0 ? (
                  <rect x={x0} y={yGreen} width={w} height={gh} fill="rgb(16 185 129)" />
                ) : null}
                {uh > 0 ? (
                  <rect x={x0} y={yBlue} width={w} height={uh} fill="rgb(59 130 246)" />
                ) : null}
              </g>
            )
          })}

          {markerPositions.map((m) => {
            const markerVal = m.xPct / 100
            const x = transformX(markerVal)
            return (
              <g key={m.kind}>
                <title>{m.label}</title>
                {m.kind === 'current' ? (
                  <line x1={x} x2={x} y1={topPad} y2={topPad + chartH} stroke="rgba(55,65,81,0.85)" strokeWidth={0.6} />
                ) : (
                  <line x1={x} x2={x} y1={topPad} y2={topPad + chartH} stroke="rgba(37,99,235,0.85)" strokeWidth={0.6} strokeDasharray="2,2" />
                )}
              </g>
            )
          })}

          <line x1={0} x2={viewW} y1={topPad + chartH} y2={topPad + chartH} stroke="rgba(229,231,235,1)" strokeWidth={0.6} />
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
  useLogScale = false,
) {
  const safeBins = Array.isArray(bins) ? bins : []
  const { markerPositions } = markerList(markers)

  const viewW = 100
  const viewH = 38
  const topPad = 2
  const chartH = 30

  // X axis is always linear; log scale only applies to Y
  const transformX = (v: number) => v * viewW

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
    const x = transformX(mid).toFixed(4)
    const y = (topPad + (1 - clamp01(share)) * chartH).toFixed(4)
    points.push(`${x},${y}`)
  }

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] text-gray-500">
          Disagreement share by confidence bin {useLogScale ? '· log scale' : ''}
        </div>
        <div className="text-[10px] text-gray-400">0–100%</div>
      </div>
      <div className="mt-1">
        <svg viewBox={`0 0 ${viewW} ${viewH}`} width="100%" height={viewH} preserveAspectRatio="none">
          <line x1={0} x2={viewW} y1={topPad} y2={topPad} stroke="rgba(229,231,235,1)" strokeWidth={0.6} />
          <line x1={0} x2={viewW} y1={topPad + chartH} y2={topPad + chartH} stroke="rgba(229,231,235,1)" strokeWidth={0.6} />
          {markerPositions.map((m) => {
            const markerVal = m.xPct / 100
            const x = transformX(markerVal)
            return m.kind === 'current' ? (
              <line key={m.kind} x1={x} x2={x} y1={topPad} y2={topPad + chartH} stroke="rgba(55,65,81,0.6)" strokeWidth={0.6} />
            ) : (
              <line key={m.kind} x1={x} x2={x} y1={topPad} y2={topPad + chartH} stroke="rgba(37,99,235,0.65)" strokeWidth={0.6} strokeDasharray="2,2" />
            )
          })}
          {points.length ? (
            <polyline fill="none" stroke="rgb(244 63 94)" strokeWidth="1.6" points={points.join(' ')} />
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
  hist: HistogramBin[],
  markers?: ThresholdMarkers,
  useLogScale = false,
) {
  const bins = Array.isArray(hist) ? hist : []
  return renderStackedHistogramSvg(bins, markers, useLogScale)
}

// --- Small sample warning component ---
function SmallSampleWarning({ n }: { n: number }) {
  if (n >= 30) return null
  return (
    <div className="mt-1 flex items-center gap-1 rounded bg-amber-50 px-2 py-1 text-[10px] text-amber-700">
      <svg className="h-3 w-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
      </svg>
      <span>Small sample (n={n}) — metrics may not be reliable</span>
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
  const [useLogScale, setUseLogScale] = React.useState(false)

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

  // Compute aggregate metrics for natural language summary
  const avgAccuracy = React.useMemo(() => {
    if (!criterionMetrics?.length) return null
    const vals = criterionMetrics.filter((m) => typeof m.accuracy_all === 'number').map((m) => m.accuracy_all as number)
    if (!vals.length) return null
    return vals.reduce((a, b) => a + b, 0) / vals.length
  }, [criterionMetrics])

  // Post-validation system accuracy: assumes all human-reviewed queue items are corrected
  // System acc = (auto_resolved * ai_accuracy + queue) / screened
  const postValidationAccuracy = React.useMemo(() => {
    if (!criterionMetrics?.length) return null
    const perCrit = criterionMetrics
      .filter((m) => typeof m.accuracy_all === 'number' && m.has_run_count > 0)
      .map((m) => {
        const autoResolved = m.has_run_count - m.needs_human_review_count
        const sysCorrect = autoResolved * (m.accuracy_all as number) + m.needs_human_review_count
        return sysCorrect / m.has_run_count
      })
    if (!perCrit.length) return null
    return perCrit.reduce((a, b) => a + b, 0) / perCrit.length
  }, [criterionMetrics])

  const accuracyDelta = avgAccuracy !== null && postValidationAccuracy !== null
    ? Math.round((postValidationAccuracy - avgAccuracy) * 100)
    : null

  const avgF1 = React.useMemo(() => {
    if (!criterionMetrics?.length) return null
    const vals = criterionMetrics.filter((m) => typeof m.f1_score === 'number').map((m) => m.f1_score as number)
    if (!vals.length) return null
    return vals.reduce((a, b) => a + b, 0) / vals.length
  }, [criterionMetrics])

  const workloadReduction = React.useMemo(() => {
    const screened = total - notScreened
    if (screened === 0 || total === 0) return null
    return (1 - queueTotal / screened) * 100
  }, [total, notScreened, queueTotal])

  // --- Critical prompt additions editor ---
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
        const token = getAuthToken()
        const tokenType = getTokenType()
        const res = await fetch(
          `/api/can-sr/reviews/critical-prompt-additions?sr_id=${encodeURIComponent(String(srId))}`,
          {
            method: 'GET',
            headers: token ? { Authorization: `${tokenType} ${token}` } : undefined,
          },
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
      return { ...(base as any), [stepNorm]: { ...block, [criterionKey]: value } }
    })
  }

  const saveCPA = async () => {
    if (!srId) return
    if (!(stepNorm === 'l1' || stepNorm === 'l2')) return
    setSavingCPA(true)
    try {
      const token = getAuthToken()
      const tokenType = getTokenType()
      const payload = { critical_prompt_additions: criticalAdditions || { l1: {}, l2: {} } }
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
        setCriticalAdditions(j?.critical_prompt_additions || payload.critical_prompt_additions)
      }
    } finally {
      setSavingCPA(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[960px]">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-3">
            <span>{title}</span>
            <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-normal text-gray-600">
              <input
                type="checkbox"
                checked={useLogScale}
                onChange={(e) => setUseLogScale(e.target.checked)}
                className="h-3 w-3 rounded border-gray-300"
              />
              Log scale
            </label>
          </DialogTitle>
          <div className="text-xs text-gray-600">
            {stepLabel ? `${stepLabel} · ` : ''}Screening performance & workload analysis
          </div>
        </DialogHeader>

        <div className="max-h-[70vh] overflow-auto space-y-6">

          {/* ===== NATURAL LANGUAGE SUMMARY ===== */}
          {(avgAccuracy !== null || avgF1 !== null || workloadReduction !== null) ? (
            <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-4">
              <p className="text-sm text-gray-800">
                {avgAccuracy !== null ? (
                  <>The AI agrees with human reviewers <span className="font-semibold">{Math.round(avgAccuracy * 100)}%</span>{accuracyDelta !== null && accuracyDelta > 0 ? <span className="ml-1 text-emerald-600 font-medium cursor-help" title="Projected system accuracy after human validation corrects all flagged citations">(+{accuracyDelta}%)</span> : null} of the time</>
                ) : null}
                {avgF1 !== null ? (
                  <>{avgAccuracy !== null ? ' ' : ''}(F1 score: <span className="font-semibold">{Math.round(avgF1 * 100)}%</span>)</>
                ) : null}
                {avgAccuracy !== null || avgF1 !== null ? '. ' : ''}
                {workloadReduction !== null ? (
                  <>At current settings, <span className="font-semibold">{Math.round(Math.max(0, workloadReduction))}%</span> of citations are auto-resolved, with <span className="font-semibold">{queueRemaining}</span> requiring human review.</>
                ) : null}
              </p>
            </div>
          ) : null}

          {/* ===== SECTION 1: AI PERFORMANCE ===== */}
          <div>
            <div className="mb-3 flex items-center gap-2">
              <div className="h-3 w-1 rounded-full bg-indigo-500" />
              <h3 className="text-sm font-semibold text-gray-900">AI Performance</h3>
              <span className="text-[11px] text-gray-500">How accurately does the AI match human decisions?</span>
            </div>

            <div className="space-y-3">
              {(criterionMetrics || []).map((m) => {
                const accAllPct = typeof m.accuracy_all === 'number' ? m.accuracy_all * 100 : null
                const f1Pct = typeof m.f1_score === 'number' ? m.f1_score * 100 : null
                const precPct = typeof m.precision === 'number' ? m.precision * 100 : null
                const recallPct = typeof m.recall === 'number' ? m.recall * 100 : null
                const npvPct = typeof m.npv === 'number' ? m.npv * 100 : null
                const accCritPct = typeof m.accuracy_critical_agent === 'number' ? m.accuracy_critical_agent * 100 : null
                const sampleN = typeof m.human_total_count_all === 'number' ? m.human_total_count_all : (m.confusion_matrix ? m.confusion_matrix.tp + m.confusion_matrix.fp + m.confusion_matrix.fn + m.confusion_matrix.tn : 0)
                const cal = calibByKey.get(m.criterion_key)
                const live = liveByKey.get(m.criterion_key)
                const rec = cal && typeof cal.recommended_threshold === 'number' ? cal.recommended_threshold : null

                return (
                  <div key={m.criterion_key} className="rounded-lg border border-gray-100 bg-white p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-gray-900">{m.label}</div>
                        <SmallSampleWarning n={sampleN} />
                      </div>
                    </div>

                    {/* Key metrics grid */}
                    <div className="mt-3 grid grid-cols-5 gap-2">
                      <div className="rounded border border-gray-100 bg-gray-50 p-2 text-center">
                        <div className="text-[10px] text-gray-500">Accuracy</div>
                        <div className="mt-0.5 text-sm font-semibold text-gray-900">
                          {accAllPct === null ? '—' : `${accAllPct.toFixed(0)}%`}
                          {(() => {
                            if (accAllPct === null || m.has_run_count <= 0) return null
                            const autoRes = m.has_run_count - m.needs_human_review_count
                            const sysAcc = ((autoRes * (m.accuracy_all as number) + m.needs_human_review_count) / m.has_run_count) * 100
                            const delta = Math.round(sysAcc - accAllPct)
                            if (delta <= 0) return null
                            return <span className="ml-0.5 text-[10px] text-emerald-600 font-medium cursor-help" title="Projected accuracy after human validation corrects all flagged citations">+{delta}%</span>
                          })()}
                        </div>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2 text-center">
                        <div className="text-[10px] text-gray-500">F1 Score</div>
                        <div className="mt-0.5 text-sm font-semibold text-gray-900">
                          {f1Pct === null ? '—' : `${f1Pct.toFixed(0)}%`}
                        </div>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2 text-center">
                        <div className="text-[10px] text-gray-500">Recall</div>
                        <div className="mt-0.5 text-sm font-semibold text-gray-900">
                          {recallPct === null ? '—' : `${recallPct.toFixed(0)}%`}
                        </div>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2 text-center">
                        <div className="text-[10px] text-gray-500">Precision</div>
                        <div className="mt-0.5 text-sm font-semibold text-gray-900">
                          {precPct === null ? '—' : `${precPct.toFixed(0)}%`}
                        </div>
                      </div>
                      <div className="rounded border border-indigo-100 bg-indigo-50/50 p-2 text-center" title="Of papers AI excluded, what % were truly irrelevant?">
                        <div className="text-[10px] text-indigo-600">NPV</div>
                        <div className="mt-0.5 text-sm font-semibold text-indigo-900">
                          {npvPct === null ? '—' : `${npvPct.toFixed(0)}%`}
                        </div>
                      </div>
                    </div>

                    {/* Confusion matrix mini */}
                    {m.confusion_matrix ? (
                      <div className="mt-3 flex items-start gap-4">
                        <div className="rounded border border-gray-100 bg-gray-50 p-2">
                          <div className="mb-1 text-[10px] font-medium text-gray-600">Confusion Matrix</div>
                          <table className="text-[10px]">
                            <thead>
                              <tr>
                                <th className="px-1"></th>
                                <th className="px-2 text-gray-500">Human: Include</th>
                                <th className="px-2 text-gray-500">Human: Exclude</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr>
                                <td className="px-1 text-gray-500">AI: Include</td>
                                <td className="px-2 text-center font-medium text-emerald-700">{m.confusion_matrix.tp}</td>
                                <td className="px-2 text-center font-medium text-rose-600">{m.confusion_matrix.fp}</td>
                              </tr>
                              <tr>
                                <td className="px-1 text-gray-500">AI: Exclude</td>
                                <td className="px-2 text-center font-medium text-rose-600">{m.confusion_matrix.fn}</td>
                                <td className="px-2 text-center font-medium text-emerald-700">{m.confusion_matrix.tn}</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                        <div className="flex-1 space-y-1 text-[11px] text-gray-600">
                          {accCritPct !== null ? <div>Critical Agent Agreement: <span className="font-medium">{accCritPct.toFixed(0)}%</span></div> : null}
                          <div>Sample size: <span className="font-medium">n={sampleN}</span></div>
                          {cal ? <div>Validated (with human answer): {cal.validated_n}</div> : null}
                        </div>
                      </div>
                    ) : null}

                    {/* Histograms */}
                    {Array.isArray(live?.histogram) && live!.histogram.length
                      ? renderDisagreementShareChart(live!.histogram, { current: m.threshold, recommended: rec }, useLogScale)
                      : null}

                    {Array.isArray(live?.histogram) && live!.histogram.length
                      ? renderLiveConfidenceHistogram(live!.histogram, { current: m.threshold, recommended: rec }, useLogScale)
                      : null}
                  </div>
                )
              })}
            </div>
          </div>

          {/* ===== SECTION 2: WORKLOAD PROJECTION ===== */}
          <div>
            <div className="mb-3 flex items-center gap-2">
              <div className="h-3 w-1 rounded-full bg-amber-500" />
              <h3 className="text-sm font-semibold text-gray-900">Workload Projection</h3>
              <span className="text-[11px] text-gray-500">Impact of confidence thresholds & critical agents on review queue</span>
            </div>

            {/* Summary cards */}
            <div className="grid grid-cols-4 gap-3">
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <div className="text-[11px] text-gray-500">Workload Reduction</div>
                <div className="mt-1 text-lg font-semibold text-gray-900">
                  {workloadReduction === null ? '—' : `${Math.round(Math.max(0, workloadReduction))}%`}
                </div>
                <div className="mt-1 text-[10px] text-gray-500">of screened citations auto-resolved</div>
                {postValidationAccuracy !== null && avgAccuracy !== null && accuracyDelta !== null && accuracyDelta > 0 ? (
                  <div className="mt-1.5 text-[10px] text-emerald-600 font-medium cursor-help" title="Effective system accuracy after human validation corrects all flagged citations">
                    System accuracy: {Math.round(postValidationAccuracy * 100)}% <span className="text-emerald-500">(+{accuracyDelta}%)</span>
                  </div>
                ) : null}
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <div className="text-[11px] text-gray-500">Human Review Queue</div>
                <div className="mt-1 text-lg font-semibold text-gray-900">{queueRemaining}</div>
                <div className="mt-1 text-[10px] text-gray-500">remaining (of {queueTotal} flagged)</div>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <div className="text-[11px] text-gray-500">Auto-excluded</div>
                <div className="mt-1 text-lg font-semibold text-gray-900">{summary?.auto_excluded ?? 0}</div>
                <div className="mt-1 text-[10px] text-gray-500">confident exclude + critical agrees</div>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <div className="text-[11px] text-gray-500">Not Screened Yet</div>
                <div className="mt-1 text-lg font-semibold text-gray-900">{notScreened}</div>
                <div className="mt-1 text-[10px] text-gray-500">
                  {notScreenedPct === null ? '—' : `${notScreenedPct.toFixed(1)}% of SR`}
                </div>
              </div>
            </div>

            {/* Per-criterion workload details */}
            <div className="mt-4 space-y-2">
              {(criterionMetrics || []).map((m) => {
                const cal = calibByKey.get(m.criterion_key)
                const rec = cal && typeof cal.recommended_threshold === 'number' ? cal.recommended_threshold : null
                const curve = Array.isArray(cal?.curve) ? cal!.curve : []
                const recPoint = rec === null ? null : curve.find((p) => Math.abs(p.threshold - rec) < 1e-9) || null
                const wr = recPoint && typeof recPoint.workload_reduction === 'number' ? recPoint.workload_reduction * 100 : null
                const recRecall = recPoint && typeof recPoint.recall === 'number' ? recPoint.recall * 100 : null
                const fpr = recPoint && typeof recPoint.fpr === 'number' ? recPoint.fpr * 100 : null

                return (
                  <div key={m.criterion_key} className="rounded border border-gray-100 bg-white p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="truncate text-xs font-medium text-gray-800">{m.label}</div>
                      <div className="text-[11px] text-gray-600">
                        Threshold: <span className="font-medium">{m.threshold}</span>
                        {rec !== null ? <> · Recommended: <span className="font-medium">{rec.toFixed(2)}</span></> : null}
                      </div>
                    </div>
                    <div className="mt-2 grid grid-cols-4 gap-2 text-[11px]">
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Low confidence: <span className="font-medium">{m.low_confidence_count}</span>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Critical disagreements: <span className="font-medium">{m.critical_disagreement_count}</span>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Recall @ rec: <span className="font-medium">{recRecall === null ? '—' : `${recRecall.toFixed(0)}%`}</span>
                      </div>
                      <div className="rounded border border-gray-100 bg-gray-50 p-2">
                        Workload ↓ @ rec: <span className="font-medium">{wr === null ? '—' : `${wr.toFixed(0)}%`}</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* ===== CRITICAL PROMPT ADDITIONS ===== */}
          {(stepNorm === 'l1' || stepNorm === 'l2') && criterionMetrics?.length ? (
            <div>
              <div className="mb-3 flex items-center gap-2">
                <div className="h-3 w-1 rounded-full bg-gray-400" />
                <h3 className="text-sm font-semibold text-gray-900">Critical Prompt</h3>
              </div>
              <div className="space-y-2">
                {(criterionMetrics || []).map((m) => (
                  <div key={m.criterion_key} className="rounded border border-gray-100 bg-gray-50 p-2">
                    <div className="mb-1 text-[11px] font-medium text-gray-700">{m.label}</div>
                    <textarea
                      value={String((criticalAdditions as any)?.[stepNorm]?.[m.criterion_key] || '')}
                      onChange={(e) => updateAddition(m.criterion_key, e.target.value)}
                      rows={2}
                      className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-[11px]"
                      placeholder="Add SR-specific instructions for the critical prompt."
                    />
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-center justify-between gap-3">
                <div className="text-xs text-gray-600">
                  {loadingCPA ? 'Loading…' : 'Edit above, then save.'}
                </div>
                <button
                  onClick={saveCPA}
                  disabled={savingCPA || loadingCPA || !srId}
                  className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                >
                  {savingCPA ? 'Saving…' : 'Save critical additions'}
                </button>
              </div>
            </div>
          ) : null}

        </div>
      </DialogContent>
    </Dialog>
  )
}
