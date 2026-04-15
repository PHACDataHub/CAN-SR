'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { getAuthToken, getTokenType } from '@/lib/auth'
import PagedList from '@/components/can-sr/PagedList'
import { Bot, Check, Wand2 } from 'lucide-react'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'
import { ModelSelector } from '@/components/chat'
import { toast } from 'react-hot-toast'
import ScreeningMetricsPanel, {
  type ScreeningMetricsStats,
  type ScreeningMetricsSummary,
  type ScreeningCriterionMetrics,
  type CalibrationCriterion,
} from '@/components/can-sr/ScreeningMetricsPanel'
import ScreeningMetricsModal from '@/components/can-sr/ScreeningMetricsModal'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
// Progress UI is shown in the bottom-right floating panel; keep list view clean.

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const tokenType = getTokenType()
  return token ? { Authorization: `${tokenType} ${token}` } : {}
}

type CriteriaData = {
  questions: string[]
  possible_answers: string[][]
  include: string[] | null
}

type CitationListData = {
  screeningStep: string
  pageview: string
  buildCitationAiCalls?: BuildCitationAiCalls
}

export type AiCall = {
  key: string
  label: string
  run: () => Promise<void>
}

export type BuildCitationAiCalls = (args: {
  srId: string
  citationId: number
  screeningStep: string
  model: string
  criteria: CriteriaData
  getAuthHeaders: () => Record<string, string>
  dict: any
}) => Promise<AiCall[]> | AiCall[]

export default function CitationsListPage({
  screeningStep,
  pageview,
  buildCitationAiCalls,
}: CitationListData) {
  // buildCitationAiCalls kept for backwards-compatibility with older page views.
  void buildCitationAiCalls
  const searchParams = useSearchParams()
  const router = useRouter()
  const srId = searchParams?.get('sr_id')
  const dict = useDictionary()

  const [citationIds, setCitationIds] = useState<number[] | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [exporting, setExporting] = useState<boolean>(false)
  const [runAllModalOpen, setRunAllModalOpen] = useState<boolean>(false)
  const [selectedModel, setSelectedModel] = useState<string>('gpt-5-mini')
  const [error, setError] = useState<string | null>(null)
  const [criteriaData, setCriteriaData] = useState<CriteriaData | null>()

  // Phase 1 single-threshold is deprecated; kept for backward compatibility.
  const [threshold, setThreshold] = useState<number>(0.9)
  const [filterMode, setFilterMode] = useState<'needs' | 'validated' | 'unvalidated' | 'not_screened' | 'all'>('all')
  // page-local stats no longer shown (SR-wide progress bar is in metrics panel)
  const [_pageStats, setPageStats] = useState<ScreeningMetricsStats | undefined>(undefined)

  // Phase 2 metrics (SR-wide)
  const [srMetricsSummary, setSrMetricsSummary] = useState<ScreeningMetricsSummary | undefined>(undefined)
  const [srCriterionMetrics, setSrCriterionMetrics] = useState<ScreeningCriterionMetrics[] | undefined>(undefined)
  const [srCalibration, setSrCalibration] = useState<CalibrationCriterion[] | undefined>(undefined)
  const [_srThresholds, setSrThresholds] = useState<Record<string, any> | null>(null)

  // Backend warnings (e.g., legacy data needs run-all)
  const [srWarnings, setSrWarnings] = useState<any[] | null>(null)

  const legacyWarning = useMemo(() => {
    const ws = Array.isArray(srWarnings) ? srWarnings : []
    return (
      ws.find((w) => String(w?.code || '').toUpperCase() === 'LEGACY_DATA_NEEDS_RUN_ALL') ||
      null
    )
  }, [srWarnings])

  // Silence eslint unused warnings for state that is intentionally retained for backwards-compatibility.
  void _pageStats
  void _srThresholds
  const [metricsRefreshKey, setMetricsRefreshKey] = useState<number>(0)

  const [metricsDrawerOpen, setMetricsDrawerOpen] = useState<boolean>(false)

  // Draft editing: user can adjust thresholds locally, then click Save.
  const [draftThresholds, setDraftThresholds] = useState<Record<string, any> | null>(null)
  const [thresholdsDirty, setThresholdsDirty] = useState<boolean>(false)
  const [savingThresholds, setSavingThresholds] = useState<boolean>(false)

  // Run-all job tracking (persist across modal close / refresh)
  const [runAllForce, setRunAllForce] = useState<boolean>(false)
  const [runAllJobId, setRunAllJobId] = useState<string | null>(null)
  const [runAllJob, setRunAllJob] = useState<any | null>(null)
  const [runAllStarting, setRunAllStarting] = useState<boolean>(false)

  const runAllStorageKey = useMemo(() => {
    if (!srId) return null
    return `runAllJob:${srId}:${screeningStep}`
  }, [srId, screeningStep])

  const clearRunAll = useCallback(() => {
    try {
      if (runAllStorageKey) window.localStorage.removeItem(runAllStorageKey)
    } catch {
      // ignore
    }
    setRunAllJobId(null)
    setRunAllJob(null)
  }, [runAllStorageKey])

  const displayMap: Record<string, string> = {
    l1: dict.screening.titleAbstract,
    l2: dict.screening.fullText,
    extract: dict.screening.parameterExtraction,
  }

  useEffect(() => {
    if (!srId) {
      router.replace('/can-sr')
      throw new Error('Missing srId: Redirecting to /can-sr')
    }

    const loadCitations = async () => {
      setLoading(true)
      setError(null)
      try {
        const headers = getAuthHeaders()
        let filterStep = ''
        if (screeningStep === 'l2') {
          filterStep = 'l1'
        } else if (screeningStep === 'extract') {
          filterStep = 'l2'
        }
        const res = await fetch(
          `/api/can-sr/citations/list?sr_id=${encodeURIComponent(srId)}&filter=${encodeURIComponent(filterStep)}`,
          { method: 'GET', headers },
        )
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          const errMsg =
            data?.error ||
            data?.detail ||
            `Failed to load citations (${res.status})`
          setError(errMsg)
          setCitationIds([])
        } else {
          setCitationIds(data?.citation_ids || [])
        }
      } catch (err: any) {
        console.error('Failed to fetch citations', err)
        setError(err?.message || 'Network error while fetching citations')
        setCitationIds([])
      } finally {
        setLoading(false)
      }
    }

    const loadCriteria = async () => {
      const headers = getAuthHeaders()
      const res = await fetch(
        `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}`,
        { headers },
      )
      const data = await res.json().catch(() => ({}))

      if (!res.ok) {
        console.warn('Failed to load criteria', data)
        setCriteriaData(null)
      } else {
        const parsed = data?.criteria_parsed || data?.criteria || {}
        const screenInfo = parsed?.[screeningStep] || parsed
        setCriteriaData({
          questions: screenInfo?.questions || [],
          possible_answers: screenInfo?.possible_answers || [],
          include: screenInfo?.include || [],
        })
      }
    }

    loadCriteria()
    loadCitations()
  }, [srId, router, screeningStep])

  // Load SR thresholds + metrics (L1/L2 only)
  useEffect(() => {
    if (!srId) return
    if (!(screeningStep === 'l1' || screeningStep === 'l2')) {
      setSrMetricsSummary(undefined)
      setSrCriterionMetrics(undefined)
      setSrThresholds(null)
      return
    }

    const load = async () => {
      try {
        const headers = getAuthHeaders()

        // 1) thresholds
        const tRes = await fetch(
          `/api/can-sr/reviews/thresholds?sr_id=${encodeURIComponent(srId)}`,
          { method: 'GET', headers },
        )
        const tJson = await tRes.json().catch(() => ({}))
        const thresholds = (tRes.ok ? tJson?.screening_thresholds : null) || {}
        setSrThresholds(typeof thresholds === 'object' && thresholds ? thresholds : {})
        setDraftThresholds(typeof thresholds === 'object' && thresholds ? thresholds : {})
        setThresholdsDirty(false)

        // 2) metrics
        const mRes = await fetch(
          `/api/can-sr/screen/metrics?sr_id=${encodeURIComponent(srId)}&step=${encodeURIComponent(
            screeningStep,
          )}`,
          { method: 'GET', headers },
        )
        const mJson = await mRes.json().catch(() => ({}))
        if (mRes.ok) {
          const stepBlock = mJson?.steps?.[screeningStep]
          setSrMetricsSummary(stepBlock?.summary)
          setSrCriterionMetrics(stepBlock?.criteria)
          setSrWarnings(Array.isArray(mJson?.warnings) ? mJson.warnings : null)
        } else {
          setSrMetricsSummary(undefined)
          setSrCriterionMetrics(undefined)
          setSrWarnings(null)
        }

        // 3) calibration (validated set)
        const cRes = await fetch(
          `/api/can-sr/screen/calibration?sr_id=${encodeURIComponent(srId)}&step=${encodeURIComponent(
            screeningStep,
          )}`,
          { method: 'GET', headers },
        )
        const cJson = await cRes.json().catch(() => ({}))
        if (cRes.ok && Array.isArray(cJson?.criteria)) {
          setSrCalibration(cJson.criteria as CalibrationCriterion[])
        } else {
          setSrCalibration(undefined)
        }
      } catch {
        setSrMetricsSummary(undefined)
        setSrCriterionMetrics(undefined)
        setSrCalibration(undefined)
        setSrThresholds(null)
        setSrWarnings(null)
      }
    }
    load()
  }, [srId, screeningStep, metricsRefreshKey])

  const persistThresholds = useCallback(
    async (nextThresholds: Record<string, any>) => {
      if (!srId) return
      try {
        setSavingThresholds(true)
        const headers = { ...getAuthHeaders(), 'Content-Type': 'application/json' }
        const res = await fetch(
          `/api/can-sr/reviews/thresholds?sr_id=${encodeURIComponent(srId)}`,
          {
            method: 'PUT',
            headers,
            body: JSON.stringify({ screening_thresholds: nextThresholds }),
          },
        )
        const j = await res.json().catch(() => ({}))
        if (res.ok) {
          setSrThresholds(j?.screening_thresholds || nextThresholds)
          setDraftThresholds(j?.screening_thresholds || nextThresholds)
          setThresholdsDirty(false)
          // Refresh metrics so counts reflect the new thresholds.
          setMetricsRefreshKey((k) => k + 1)
        }
      } catch {
        // ignore
      } finally {
        setSavingThresholds(false)
      }
    },
    [srId],
  )

  // Restore persisted run-all job id
  useEffect(() => {
    if (!runAllStorageKey) return
    try {
      const stored = window.localStorage.getItem(runAllStorageKey)
      if (stored) setRunAllJobId(stored)
    } catch {
      // ignore
    }
  }, [runAllStorageKey])

  // Poll job status when we have a job id
  useEffect(() => {
    if (!runAllJobId) return
    let alive = true
    const headers = getAuthHeaders()

    const fetchStatus = async () => {
      const res = await fetch(
        `/api/can-sr/jobs/run-all/status?job_id=${encodeURIComponent(runAllJobId)}`,
        { method: 'GET', headers },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.detail || data?.error || `Status failed (${res.status})`)
      }
      return data
    }

    const tick = async () => {
      try {
        const latest = await fetchStatus()
        if (!alive) return
        setRunAllJob(latest)
        const st = String(latest?.status || '').toLowerCase()
        if (['done', 'failed', 'canceled'].includes(st)) {
          clearRunAll()
        }
      } catch (e: any) {
        // Surface errors but keep polling
        if (!alive) return
        console.warn('Run-all polling error', e)
      }
    }

    // immediate tick + interval
    tick()
    const interval = window.setInterval(tick, 5000)
    return () => {
      alive = false
      window.clearInterval(interval)
    }
  }, [runAllJobId, runAllStorageKey, clearRunAll])
  

  const hasActiveRunAll = useMemo(() => {
    const st = String(runAllJob?.status || '').toLowerCase()
    return !!runAllJobId && ['queued', 'running', 'paused'].includes(st)
  }, [runAllJobId, runAllJob])

  const startRunAll = async () => {
    if (!srId) return
    if (hasActiveRunAll) {
      setRunAllModalOpen(false)
      return
    }
    setRunAllStarting(true)
    setError(null)
    try {
      const headers = { ...getAuthHeaders(), 'Content-Type': 'application/json' }
      const sendExplicitIds = screeningStep === 'l1'
      const res = await fetch(`/api/can-sr/jobs/run-all/start?sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({
            step: (screeningStep as any) || 'l1',
            model: selectedModel,
            force: runAllForce,
            chunk_size: 5,
            // For l1 we explicitly send the filtered list IDs (entire list, not just page).
            // For l2/extract we let the backend compute eligible IDs so it can enforce
            // the PDF/fulltext requirement.
            citation_ids: sendExplicitIds ? (citationIds || []) : undefined,
          }),
        },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.detail || data?.error || `Start failed (${res.status})`)
      }

      // Notify floating panel to refresh once (it stops polling when empty/paused).
      try {
        window.dispatchEvent(new Event('run-all:changed'))
      } catch {
        // ignore
      }

      const jid = data?.job_id
      if (!jid) throw new Error('Missing job_id from server')

      // If server says a job already exists, attach UI to that job and warn.
      const alreadyRunning = Boolean(data?.already_running || data?.existing)
      if (alreadyRunning) {
        toast.error(dict?.screening?.onlyOneJobAtATime || 'Only one job can be running at a time', {
          duration: 5000,
        })
      }

      setRunAllJobId(jid)
      // Optimistic: show banner immediately (polling will reconcile).
      // For server-computed (l2/extract) the total is initially unknown.
      setRunAllJob({
        job_id: jid,
        status: sendExplicitIds ? 'running' : 'queued',
        total: sendExplicitIds ? (citationIds || []).length : 0,
        done: 0,
        skipped: 0,
        failed: 0,
      })
      try {
        if (runAllStorageKey) window.localStorage.setItem(runAllStorageKey, jid)
      } catch {
        // ignore
      }
      setRunAllModalOpen(false)
    } catch (e: any) {
      setError(e?.message || 'Failed to start run-all')
    } finally {
      setRunAllStarting(false)
    }
  }

  const canRunAllServerSide = useMemo(() => {
    if (!srId) return false
    if (loading) return false
    if (!citationIds || citationIds.length === 0) return false
    // Server-side run-all does not depend on buildCitationAiCalls/criteriaData; backend reads SR criteria.
    return true
  }, [srId, loading, citationIds])

  // Note: detailed progress UI lives in RunAllFloatingPanel.

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title={displayMap[screeningStep]}
        backHref={`/can-sr/sr?sr_id=${encodeURIComponent(srId || '')}`}
        right={
          <ModelSelector selectedModel={selectedModel} onModelChange={setSelectedModel} />
        }
      />

      {/*
        Layout: left floating/side metrics module + right list.
        (A true fixed overlay can be added later; this keeps it responsive and simple.)
      */}
      <main className="mx-auto max-w-7xl px-6 py-10">
        {legacyWarning ? (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <div className="font-medium">Legacy screening data detected</div>
            <div className="mt-1 text-amber-800">
              {String(legacyWarning?.message ||
                'This SR has legacy llm_* outputs but no agentic runs. Please run Run-all to regenerate results.')}
            </div>
            <div className="mt-2 text-[12px] text-amber-800">
              Tip: when legacy data is detected, Run-all will automatically force overwrite to generate real agent runs.
            </div>
          </div>
        ) : null}

        <ScreeningMetricsModal
          open={metricsDrawerOpen}
          onOpenChange={setMetricsDrawerOpen}
          title={dict?.screening?.metricsTitle || 'Screening metrics'}
          stepLabel={displayMap[screeningStep]}
          summary={srMetricsSummary}
          criterionMetrics={srCriterionMetrics}
          calibration={srCalibration}
          srId={srId}
          step={screeningStep}
        />

        <Dialog open={runAllModalOpen} onOpenChange={() => setRunAllModalOpen(false)}>
          <DialogContent className="sm:max-w-[560px]">
            <DialogHeader>
              <DialogTitle>{dict?.screening?.runAllAI || 'Run all AI'}</DialogTitle>
              <DialogDescription>
                {screeningStep === 'l1'
                  ? dict?.screening?.runAllL1Desc ||
                    'Runs title/abstract screening on all citations in the list.'
                  : screeningStep === 'l2'
                    ? dict?.screening?.runAllL2Desc ||
                      'Runs full-text screening on citations that passed L1 and have an uploaded PDF.'
                    : dict?.screening?.runAllExtractDesc ||
                      'Runs parameter extraction on citations that passed L2 and have an uploaded PDF.'}
              </DialogDescription>
            </DialogHeader>

            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={runAllForce}
                onChange={(e) => setRunAllForce(e.target.checked)}
              />
              {dict?.screening?.forceRerun ||
                'Force re-run (overwrite existing AI results)'}
            </label>

            <DialogFooter className="gap-2">
              <Button variant="outline" onClick={() => setRunAllModalOpen(false)}>
                {dict?.common?.close || 'Close'}
              </Button>
              <Button onClick={startRunAll} disabled={!canRunAllServerSide || runAllStarting || hasActiveRunAll}>
                {runAllStarting
                  ? dict?.screening?.starting || 'Starting…'
                  : dict?.screening?.startRunAll || 'Start'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <div className="grid grid-cols-12 gap-6">
          <aside className="col-span-12 md:col-span-5">
            <div className="sticky top-6">
              <ScreeningMetricsPanel
                title={dict?.screening?.metricsTitle || 'Screening metrics'}
                filterMode={filterMode}
                onFilterModeChange={setFilterMode}
                onOpenDetails={() => setMetricsDrawerOpen(true)}
                stats={undefined}
                summary={srMetricsSummary}
                criterionMetrics={srCriterionMetrics}
                calibration={srCalibration}
                showFilter={false}
                thresholdsDirty={thresholdsDirty}
                savingThresholds={savingThresholds}
                onSaveThresholds={() => {
                  const next = draftThresholds && typeof draftThresholds === 'object' ? draftThresholds : {}
                  void persistThresholds(next)
                }}
                onCriterionThresholdChange={(criterionKey, v) => {
                  // Update draft per-step thresholds
                  const base = draftThresholds && typeof draftThresholds === 'object' ? { ...draftThresholds } : {}
                  const stepKey = String(screeningStep)
                  const stepMap = (base as any)[stepKey] && typeof (base as any)[stepKey] === 'object'
                    ? { ...(base as any)[stepKey] }
                    : {}
                  stepMap[criterionKey] = v
                  ;(base as any)[stepKey] = stepMap
                  setDraftThresholds(base)
                  setThresholdsDirty(true)
                }}
                onCriterionThresholdCommit={(criterionKey, v) => {
                  // Ensure draft is updated and then persist.
                  const base = draftThresholds && typeof draftThresholds === 'object' ? { ...draftThresholds } : {}
                  const stepKey = String(screeningStep)
                  const stepMap = (base as any)[stepKey] && typeof (base as any)[stepKey] === 'object'
                    ? { ...(base as any)[stepKey] }
                    : {}
                  stepMap[criterionKey] = v
                  ;(base as any)[stepKey] = stepMap
                  setDraftThresholds(base)
                  setThresholdsDirty(true)
                  void persistThresholds(base)
                }}
              />
            </div>
          </aside>

          <div className="col-span-12 md:col-span-7">
            <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">
                    {dict.screening.citationsList}
                  </h3>
                  <p className="mt-1 text-sm text-gray-600">
                    {dict.screening.citationsListDesc}
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    disabled={!canRunAllServerSide || hasActiveRunAll}
                    onClick={() => setRunAllModalOpen(true)}
                    className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
                    title={dict.screening.runAllAI}
                  >
                    <span className="inline-flex items-center gap-1">
                      {dict.screening.runAllAI}
                      <Wand2 className="h-4 w-4" />
                    </span>
                  </button>

                  <button
                    type="button"
                    disabled={!srId || exporting}
                    onClick={async () => {
                      if (!srId) return
                      try {
                        setExporting(true)
                        const headers = getAuthHeaders()
                        const res = await fetch(
                          `/api/can-sr/citations/list?action=export&sr_id=${encodeURIComponent(srId)}`,
                          { method: 'GET', headers },
                        )
                        if (!res.ok) {
                          const text = await res.text().catch(() => '')
                          throw new Error(text || `Export failed (${res.status})`)
                        }
                        const blob = await res.blob()
                        const url = window.URL.createObjectURL(blob)
                        const a = document.createElement('a')
                        a.href = url
                        a.download = `citations_${srId}.csv`
                        document.body.appendChild(a)
                        a.click()
                        a.remove()
                        window.URL.revokeObjectURL(url)
                      } catch (e: any) {
                        console.error('Export failed', e)
                        setError(e?.message || 'Export failed')
                      } finally {
                        setExporting(false)
                      }
                    }}
                    className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:bg-emerald-300"
                  >
                    {exporting ? dict.common.downloading : dict.common.export}
                  </button>

                  <div className="flex max-w-xs flex-col items-center space-y-2 rounded-md border border-gray-200 bg-gray-50 p-2">
                    <div className="flex items-center space-x-2">
                      <Bot className="h-5 w-5 text-green-600" />
                      <span className="text-sm text-gray-700">
                        {dict.screening.llmClassified}
                      </span>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Check className="h-5 w-5 text-green-600" />
                      <span className="text-sm text-gray-700">
                        {dict.screening.humanVerified}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Run-all status/controls are shown in the bottom-right floating panel. */}

              <div className="mt-6">
                {/* Filter bar moved above the list view */}
                {(screeningStep === 'l1' || screeningStep === 'l2') ? (
                  <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-gray-200 bg-white p-3">
                    <label className="text-sm text-gray-700">Filter</label>
                    <select
                      value={filterMode}
                      onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                        setFilterMode(e.target.value as any)
                      }
                      className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm"
                    >
                      <option value="all">All</option>
                      <option value="needs">Needs human review</option>
                      <option value="unvalidated">Unvalidated</option>
                      <option value="validated">Validated</option>
                      <option value="not_screened">Not screened yet</option>
                    </select>
                  </div>
                ) : null}

                {loading ? (
                  <div className="text-sm text-gray-600">
                    {dict.screening.loadingCitations}
                  </div>
                ) : error ? (
                  <div className="text-sm text-red-600">{error}</div>
                ) : citationIds && citationIds.length === 0 ? (
                  <div className="text-sm text-gray-600">
                    {dict.screening.noCitations}
                  </div>
                ) : (
                  <div>
                    <div className="mb-3 text-sm text-gray-700">
                      {dict.screening.totalCitations}{' '}
                      {citationIds ? citationIds.length : 0}
                    </div>

                    <PagedList
                      citationIds={citationIds || []}
                      srId={srId || ''}
                      questions={criteriaData?.questions || []}
                      possible_answers={criteriaData?.possible_answers || []}
                      include={criteriaData?.include || []}
                      screeningStep={screeningStep || ''}
                      pageview={pageview}
                      threshold={threshold}
                      thresholdByCriterionKey={
                        (draftThresholds && typeof draftThresholds === 'object'
                          ? (draftThresholds as any)[String(screeningStep)]
                          : null) || undefined
                      }
                      filterMode={filterMode}
                      onThresholdChange={setThreshold}
                      onFilterModeChange={setFilterMode}
                      onStatsChange={(s) => {
                        // keep state for now (used elsewhere), but do not show in metrics panel
                        setPageStats({
                          scopeLabel: 'this page',
                          total: s.total,
                          needsValidation: s.needsValidation,
                          validated: s.validated,
                          unvalidated: s.unvalidated,
                        })
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
