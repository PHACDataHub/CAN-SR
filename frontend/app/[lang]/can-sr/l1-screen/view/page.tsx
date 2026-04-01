'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { ModelSelector } from '@/components/chat'
import { getAuthToken, getTokenType } from '@/lib/auth'
import { Wand2 } from 'lucide-react'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

/*
  Title & Abstract single-citation viewer for L1 screening.

  Responsibilities implemented here:
  - Load citation by citation_id via frontend proxy (/api/can-sr/citations/get)
  - Load parsed criteria for the review via frontend proxy (/api/can-sr/reviews/create?sr_id=...&criteria_parsed=1)
  - Render a workspace (left) that shows title + abstract (flexible container for future PDF/text viewers)
  - Render a selection sidebar (right) with one section per L1 question:
      - Dropdown containing options from criteriaData.possible_answers
      - Default selection set to AI answer from the citation row (column name computed via snake_case_column)
      - "Classify" button that calls the backend screen classify endpoint and updates the AI panel
  - If an AI answer exists for that question, show a collapsible panel containing the parsed LLM JSON
    (expected fields: selected, explanation, confidence, llm_raw/)
  - Keep the code simple and add short comments to make future componentization straightforward.
*/

/* Helpers */

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const tokenType = getTokenType()
  return token ? { Authorization: `${tokenType} ${token}` } : {}
}

/**
 * Frontend approximation of backend snake_case_column.
 * - Lowercase, non-word -> underscore, collapse underscores
 * - Prefix with "llm_"
 */
function snakeCaseColumn(name: string) {
  if (!name) return 'llm_col'
  let s = name.trim().toLowerCase()
  s = s.replace(/[^\w]+/g, '_')
  s = s.replace(/_+/g, '_').replace(/^_+|_+$/g, '')
  return `llm_${s}`.slice(0, 60)
}

/**
 * Human classification column for screening (mirrors llm_ prefix but with human_).
 * Example: question -> llm_question, human_question
 */
function humanScreenColumn(name: string) {
  const base = snakeCaseColumn(name)
  return base.replace(/^llm_/, 'human_')
}

type ValidationEntry = { user: string; validated_at: string }

function parseValidations(v: any): ValidationEntry[] {
  if (!v) return []
  try {
    const parsed = typeof v === 'string' ? JSON.parse(v) : v
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((x: any) => x && typeof x === 'object')
      .map((x: any) => ({
        user: String(x.user ?? x.email ?? x.validated_by ?? ''),
        validated_at: String(x.validated_at ?? x.timestamp ?? ''),
      }))
      .filter((x: any) => x.user)
  } catch {
    return []
  }
}

function formatValidationDate(v: string): string {
  if (!v) return ''
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  return d.toLocaleString()
}

/* Types for local clarity */
type CriteriaData = {
  questions: string[]
  possible_answers: string[][]
}

type LatestAgentRun = {
  citation_id: number
  criterion_key: string
  stage: 'screening' | 'critical' | string
  answer?: string | null
  confidence?: number | null
  rationale?: string | null
  created_at?: string
}

/* Main page component */
export default function CanSrL1ScreenPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const citationId = searchParams?.get('citation_id')
  const thresholdParam = searchParams?.get('threshold')
  const threshold = useMemo(() => {
    const v = Number(thresholdParam)
    return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0.9
  }, [thresholdParam])
  // Get current language to keep language when navigating (must be unconditional hook call)
  const { lang } = useParams<{ lang: string }>()
  const [selectedModel, setSelectedModel] = useState('gpt-5-mini')
  const dict = useDictionary()

  // Data states
  const [citation, setCitation] = useState<Record<string, any> | null>(null)
  const [criteriaData, setCriteriaData] = useState<CriteriaData | null>(null)
  const [loadingCitation, setLoadingCitation] = useState(false)
  const [loadingCriteria, setLoadingCriteria] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Navigation list (to ensure Prev/Next follows the filtered list, not numeric id)
  const [citationIdList, setCitationIdList] = useState<number[]>([])

  // Autosave indicator per question
  const [saveStatus, setSaveStatus] = useState<Record<number, 'idle' | 'saving' | 'saved' | 'error'>>({})

  // UI state: human selections keyed by question index
  const [selections, setSelections] = useState<Record<number, string>>({})
  // AI panel state: parsed llm JSON per question index
  const [aiPanels, setAiPanels] = useState<Record<number, any>>({})
  // Collapsible open state for LLM panels
  const [panelOpen, setPanelOpen] = useState<Record<number, boolean>>({})

  // Agentic runs (screening_agent_runs) for this citation
  const [agentRuns, setAgentRuns] = useState<LatestAgentRun[]>([])
  const [loadingRuns, setLoadingRuns] = useState(false)

  const [validating, setValidating] = useState(false)
  const [userEmail, setUserEmail] = useState<string | null>(null)

  const l1Validations = useMemo(() => parseValidations((citation as any)?.l1_validations), [citation])
  const l1Checked = useMemo(() => {
    const me = String(userEmail || '')
    if (!me) return false
    return l1Validations.some((v) => v.user === me)
  }, [l1Validations, userEmail])
  const l1ValidationsSorted = useMemo(() => {
    return [...l1Validations].sort((a, b) => String(b.validated_at || '').localeCompare(String(a.validated_at || '')))
  }, [l1Validations])

  useEffect(() => {
    if (!srId || !citationId) {
      router.replace('/can-sr')
      return
    }
  }, [srId, citationId, router])

  // Load the citation id list for navigation
  useEffect(() => {
    if (!srId) return
    const loadIds = async () => {
      try {
        const headers = getAuthHeaders()
        const res = await fetch(
          `/api/can-sr/citations/list?sr_id=${encodeURIComponent(srId)}`,
          { method: 'GET', headers },
        )
        const data = await res.json().catch(() => ({}))
        if (res.ok && Array.isArray(data?.citation_ids)) {
          setCitationIdList(data.citation_ids)
        } else {
          setCitationIdList([])
        }
      } catch {
        setCitationIdList([])
      }
    }
    loadIds()
  }, [srId])

  // Fetch current user email for the "Validated by [UserEmail]" checkbox label.
  useEffect(() => {
    const loadMe = async () => {
      try {
        const headers = { ...getAuthHeaders() }
        const res = await fetch('/api/auth/me', { method: 'GET', headers })
        const data = await res.json().catch(() => ({}))
        if (res.ok) {
          setUserEmail(String(data?.user?.email || data?.email || ''))
        }
      } catch {
        // ignore
      }
    }
    loadMe()
  }, [])

  // Load citation row
  // Extracted fetch function so we can re-use it when navigating between citations
  async function fetchCitationById(id: string) {
    if (!srId || !id) return
    setLoadingCitation(true)
    try {
      const headers = getAuthHeaders()
      const res = await fetch(
        `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
          id,
        )}`,
        { method: 'GET', headers },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(
          data?.error ||
            data?.detail ||
            `Failed to load citation (${res.status})`,
        )
        setCitation(null)
      } else {
        setCitation(data || null)
      }
    } catch (err: any) {
      console.error('Citation fetch error', err)
      setError(err?.message || 'Network error while fetching citation')
    } finally {
      setLoadingCitation(false)
    }
  }

  useEffect(() => {
    if (!srId || !citationId) return
    // fetch for current citation on mount / when params change
    fetchCitationById(citationId)
  }, [srId, citationId])

  // Load latest agent runs for this citation (screening + critical per criterion)
  useEffect(() => {
    if (!srId || !citationId) return
    const loadRuns = async () => {
      setLoadingRuns(true)
      try {
        const headers = getAuthHeaders()
        const res = await fetch(
          `/api/can-sr/screen/agent-runs/latest?sr_id=${encodeURIComponent(
            srId,
          )}&pipeline=${encodeURIComponent('title_abstract')}&citation_ids=${encodeURIComponent(
            String(citationId),
          )}`,
          { method: 'GET', headers },
        )
        const data = await res.json().catch(() => ({}))
        if (res.ok && Array.isArray(data?.runs)) {
          setAgentRuns(data.runs as LatestAgentRun[])
        } else {
          setAgentRuns([])
        }
      } catch {
        setAgentRuns([])
      } finally {
        setLoadingRuns(false)
      }
    }
    loadRuns()
  }, [srId, citationId])

  const runsByCriterion = useMemo(() => {
    const by: Record<string, { screening?: LatestAgentRun; critical?: LatestAgentRun }> = {}
    for (const r of agentRuns) {
      const key = String((r as any)?.criterion_key || '')
      if (!key) continue
      if (!by[key]) by[key] = {}
      const stage = String((r as any)?.stage || '')
      if (stage === 'screening') by[key].screening = r
      if (stage === 'critical') by[key].critical = r
    }
    return by
  }, [agentRuns])

  // Load parsed criteria (L1)
  useEffect(() => {
    if (!srId) return
    const load = async () => {
      setLoadingCriteria(true)
      try {
        const headers = getAuthHeaders()
        // Use criteria_parsed=1 so backend proxy returns parsed structure when available
        const res = await fetch(
          `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}&criteria_parsed=1`,
          { method: 'GET', headers },
        )
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          console.warn('Failed to load criteria', data)
          setCriteriaData(null)
        } else {
          // Expecting srData.criteria_parsed.l1 or srData.criteria_parsed
          const parsed = data?.criteria_parsed || data?.criteria || {}
          const l1 = parsed?.l1 || parsed
          if (
            l1 &&
            Array.isArray(l1?.questions) &&
            Array.isArray(l1?.possible_answers)
          ) {
            setCriteriaData({
              questions: l1.questions,
              possible_answers: l1.possible_answers,
            })
          } else {
            // If structure is different attempt best-effort mapping
            const questions = l1?.questions || []
            const possible_answers = l1?.possible_answers || []
            setCriteriaData({
              questions: Array.isArray(questions) ? questions : [],
              possible_answers: Array.isArray(possible_answers)
                ? possible_answers
                : [],
            })
          }
        }
      } catch (err) {
        console.error('Criteria fetch error', err)
        setCriteriaData(null)
      } finally {
        setLoadingCriteria(false)
      }
    }
    load()
  }, [srId])

  // When citation + criteria are loaded, initialize selection defaults.
  // IMPORTANT: Human selections must never be overwritten by AI. So:
  // - Dropdown selection is initialized from human_* when present
  // - AI panel is initialized from llm_* when present
  // - If human_* missing, we may show llm_* as a suggested default (UI-only)
  useEffect(() => {
    if (!citation || !criteriaData) return

    const newSelections: Record<number, string> = {}
    const newAiPanels: Record<number, any> = {}
    const newPanelOpen: Record<number, boolean> = {}

    criteriaData.questions.forEach((q: string, idx: number) => {
      const llmCol = snakeCaseColumn(q)
      const humanCol = humanScreenColumn(q)

      const humanRaw = (citation as any)?.[humanCol]
      const llmRaw = (citation as any)?.[llmCol]

      const parseMaybeJson = (v: any) => {
        if (v === undefined || v === null) return null
        if (typeof v === 'string') {
          try {
            return JSON.parse(v)
          } catch {
            return v
          }
        }
        return v
      }

      const humanParsed = parseMaybeJson(humanRaw)
      const llmParsed = parseMaybeJson(llmRaw)

      // 1) Prefer human_* for dropdown
      if (humanParsed && typeof humanParsed === 'object' && (humanParsed as any).selected !== undefined) {
        newSelections[idx] = (humanParsed as any).selected
      } else if (typeof humanParsed === 'string' && humanParsed) {
        newSelections[idx] = humanParsed
      }

      // 2) Always populate AI panel from llm_* when available
      if (llmParsed && typeof llmParsed === 'object') {
        newAiPanels[idx] = llmParsed
        newPanelOpen[idx] = false
      } else if (typeof llmParsed === 'string' && llmParsed) {
        newAiPanels[idx] = { selected: llmParsed }
        newPanelOpen[idx] = false
      }

      // 3) If no human selection exists, allow llm_* to prefill the dropdown (UI-only).
      const hasSelection = newSelections[idx] !== undefined && newSelections[idx] !== ''
      if (!hasSelection) {
        const aiSelected =
          newAiPanels[idx] && typeof (newAiPanels[idx] as any).selected === 'string'
            ? (newAiPanels[idx] as any).selected
            : null
        if (aiSelected) newSelections[idx] = aiSelected
      }
    })

    setSelections((prev) => ({ ...newSelections, ...prev }))
    setAiPanels((prev) => ({ ...newAiPanels, ...prev }))
    setPanelOpen((prev) => ({ ...newPanelOpen, ...prev }))
  }, [citation, criteriaData])

  // Handler: change human selection
  // When a human picks an option we persist it via the frontend proxy -> backend human_classify endpoint.
  async function postHumanClassifyPayload(
    question: string,
    selected: string,
    explanation?: string,
    confidence?: number,
  ) {
    if (!srId || !citationId) return
    try {
      const headers = {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      }
      const payload: Record<string, any> = {
        question,
        selected,
        explanation: explanation ?? '',
        confidence: confidence ?? null,
        //todo: change based on step
        screening_step: 'l1',
      }
      // Forward to frontend proxy which requires Authorization header (getAuthHeaders provides it when available)
      const res = await fetch(
        `/api/can-sr/screen?action=human_classify&sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
          citationId,
        )}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify(payload),
        },
      )
      return res.ok
    } catch (err) {
      console.error('human_classify post error', err)
      return false
    }
  }

  async function onSelectOption(questionIndex: number, value: string) {
    // Update UI immediately
    setSelections((prev) => ({ ...prev, [questionIndex]: value }))

    setSaveStatus((prev) => ({ ...prev, [questionIndex]: 'saving' }))

    // Persist human selection in background (fire-and-forget)
    if (!criteriaData) return
    const question = criteriaData.questions[questionIndex]
    const ok = await postHumanClassifyPayload(question, value)
    setSaveStatus((prev) => ({ ...prev, [questionIndex]: ok ? 'saved' : 'error' }))
  }

  // Handler: call backend classify endpoint for a single question
  async function classifyQuestion(questionIndex: number) {
    if (!srId || !citationId || !criteriaData) return
    try {
      const headers = {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      }

      // Phase 1->2 wiring: reuse the existing per-question “AI” button, but call the
      // agentic orchestrator endpoint which runs BOTH screening + critical and persists
      // them to screening_agent_runs.
      const res = await fetch('/api/can-sr/screen/title-abstract/run', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          sr_id: srId,
          citation_id: Number(citationId),
          model: selectedModel,
          temperature: 0.0,
          max_tokens: 1200,
          prompt_version: 'v1',
        }),
      })
      await res.json().catch(() => ({}))

      // Refresh latest runs + citation row so the UI shows critical + validations immediately.
      await fetchCitationById(String(citationId))

      try {
        const r2 = await fetch(
          `/api/can-sr/screen/agent-runs/latest?sr_id=${encodeURIComponent(
            srId,
          )}&pipeline=${encodeURIComponent('title_abstract')}&citation_ids=${encodeURIComponent(
            String(citationId),
          )}`,
          { method: 'GET', headers: getAuthHeaders() },
        )
        const j2 = await r2.json().catch(() => ({}))
        if (r2.ok && Array.isArray(j2?.runs)) {
          setAgentRuns(j2.runs as LatestAgentRun[])
        }
      } catch {
        // ignore
      }
    } catch (err) {
      console.error('Classify API error', err)
    }
  }

  // Render helpers
  const workspace = useMemo(() => {
    if (error)
      return <div className="text-sm text-red-600">{error}</div>
    if (loadingCitation)
      return <div className="text-sm text-gray-600">{dict.screening.loadingCitation}</div>
    if (!citation)
      return <div className="text-sm text-gray-600">{dict.screening.citationNotFound}</div>

    return (
      <div className="space-y-3">
        <div>
          <p className="text-xs text-gray-600">Citation #{citation.id}</p>
          <h2 className="text-lg font-semibold text-gray-900">
            {citation.title}
          </h2>
        </div>

        <div className="rounded-md border border-gray-200 bg-white p-4">
          <h3 className="text-sm font-medium text-gray-800">{dict.screening.abstract}</h3>
          <p className="mt-2 text-sm whitespace-pre-wrap text-gray-800">
            {citation.abstract || dict.screening.noAbstract}
          </p>
        </div>
      </div>
    )
  }, [citation, loadingCitation, dict, error])

  if (!srId || !citationId) {
    // guard - redirect already handled in effect but keep safe render
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title={dict.screening.titleAbstract}
        backHref={`/can-sr/sr?sr_id=${encodeURIComponent(srId)}`}
        right={
          <ModelSelector
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        }
      />

      <main className="mx-auto max-w-6xl px-6 py-8">
        {/* Agentic summary + Validate */}
        <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Agentic results</h3>
              <p className="text-xs text-gray-600">
                Latest <code>screening</code> + <code>critical</code> runs per criterion.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={async () => {
                  if (!srId || !citationId) return
                  setValidating(true)
                  try {
                    const headers = {
                      'Content-Type': 'application/json',
                      ...getAuthHeaders(),
                    }
                    await fetch('/api/can-sr/screen/validate', {
                      method: 'POST',
                      headers,
                      body: JSON.stringify({
                        sr_id: srId,
                        citation_id: Number(citationId),
                        step: 'l1',
                      }),
                    })
                    // Refresh citation so validated fields appear
                    await fetchCitationById(String(citationId))
                  } finally {
                    setValidating(false)
                  }
                }}
                className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
                disabled={validating}
                type="button"
              >
                {validating ? 'Validating…' : 'Validate (L1)'}
              </button>

              {citation?.l1_validated_by ? (
                <span className="text-xs text-emerald-700">
                  Validated by {String(citation.l1_validated_by)}
                </span>
              ) : (
                <span className="text-xs text-gray-600">Not validated</span>
              )}
            </div>
          </div>

          {loadingRuns ? (
            <div className="mt-3 text-sm text-gray-600">Loading agent runs…</div>
          ) : criteriaData?.questions?.length ? (
            <div className="mt-3 space-y-2">
              {criteriaData.questions.map((q, idx) => {
                const criterionKey = q
                  ? q
                      .trim()
                      .toLowerCase()
                      .replace(/[^\w]+/g, '_')
                      .replace(/_+/g, '_')
                      .replace(/^_+|_+$/g, '')
                      .slice(0, 56)
                  : ''

                const r = runsByCriterion[criterionKey] || {}
                const scr = r.screening
                const crit = r.critical

                const critDisagrees =
                  crit && String((crit as any)?.answer || '').trim() !== '' &&
                  String((crit as any)?.answer || '').trim() !== 'None of the above'

                return (
                  <div key={idx} className="rounded-md border border-gray-100 bg-gray-50 p-3">
                    <div className="text-sm font-medium text-gray-800">{q}</div>
                    <div className="mt-2 grid grid-cols-2 gap-3 text-xs text-gray-700">
                      <div className="rounded-md border border-gray-100 bg-white p-2">
                        <div className="font-semibold">Screening</div>
                        <div>Answer: {String((scr as any)?.answer ?? '—')}</div>
                        <div>Confidence: {String((scr as any)?.confidence ?? '—')}</div>
                      </div>
                      <div className={"rounded-md border border-gray-100 bg-white p-2 " + (critDisagrees ? 'border-amber-300 bg-amber-50' : '')}>
                        <div className="font-semibold">Critical</div>
                        <div>Answer: {String((crit as any)?.answer ?? '—')}</div>
                        <div>Confidence: {String((crit as any)?.confidence ?? '—')}</div>
                        {critDisagrees ? (
                          <div className="mt-1 font-medium text-amber-700">Disagrees</div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="mt-3 text-sm text-gray-600">No criteria loaded yet.</div>
          )}
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Workspace (left) */}
          <div className="col-span-12 md:col-span-7">
            <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
              {workspace}
            </div>
          </div>

          {/* Selection sidebar (right) */}
          <aside className="col-span-12 md:col-span-5">
            <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h4 className="text-md font-semibold text-gray-900">
                {dict.screening.selection}
              </h4>
              <p className="text-sm text-gray-600">{dict.screening.selectionDesc}</p>

              {loadingCriteria ? (
                <div className="text-sm text-gray-600">{dict.screening.loadingCriteria}</div>
              ) : !criteriaData || criteriaData.questions.length === 0 ? (
                <div className="text-sm text-gray-600">{dict.screening.noCriteria}</div>
              ) : (
                <div className="space-y-4">
                  {criteriaData.questions.map((q, idx) => {
                    const options = criteriaData.possible_answers[idx] || []
                    const current = selections[idx] ?? ''
                    const aiData = aiPanels[idx]
                    const aiSelected =
                      aiData && aiData.selected ? aiData.selected : undefined

                    // Per-question highlight when low confidence or agentic disagreement.
                    const criterionKey = q
                      ? q
                          .trim()
                          .toLowerCase()
                          .replace(/[^\w]+/g, '_')
                          .replace(/_+/g, '_')
                          .replace(/^_+|_+$/g, '')
                          .slice(0, 56)
                      : ''

                    const r = runsByCriterion[criterionKey] || {}
                    const scr = r.screening
                    const crit = r.critical
                    const scrConf = Number((scr as any)?.confidence)
                    const lowConfidence = Number.isFinite(scrConf) ? scrConf < threshold : false
                    const critAns = String((crit as any)?.answer || '').trim()
                    const critDisagrees = !!crit && critAns !== '' && critAns !== 'None of the above'
                    const needsHuman = lowConfidence || critDisagrees

                    return (
                      <div
                        key={idx}
                        className={
                          'rounded-md border p-3 ' +
                          (needsHuman ? 'border-amber-300 bg-amber-50' : 'border-gray-100')
                        }
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-800">
                              {q}
                            </p>

                            <select
                              value={current || (aiSelected ?? '')}
                              onChange={(e) =>
                                onSelectOption(idx, e.target.value)
                              }
                              className="mt-2 w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm"
                            >
                              <option value="">-- select --</option>
                              {options.map((opt: string) => (
                                <option key={opt} value={opt}>
                                  {opt}
                                </option>
                              ))}
                            </select>
                          </div>

                          <div className="ml-3 flex flex-col items-end space-y-2">
                            <button
                              onClick={() => classifyQuestion(idx)}
                              className="rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
                            >
                              <span className="inline-flex items-center gap-1">
                                AI <Wand2 className="h-3 w-3" />
                              </span>
                            </button>

                            {saveStatus[idx] === 'saving' ? (
                              <span className="text-[10px] text-gray-500">{dict.common.save}...</span>
                            ) : saveStatus[idx] === 'saved' ? (
                              <span className="text-[10px] text-emerald-600">{dict.common.done}</span>
                            ) : saveStatus[idx] === 'error' ? (
                              <span className="text-[10px] text-red-600">{dict.common.error}</span>
                            ) : null}
                          </div>
                        </div>

                        {/* AI panel: collapsible */}
                        {aiData ? (
                          <div className="mt-3">
                            <div
                              onClick={() =>
                                setPanelOpen((prev) => ({
                                  ...prev,
                                  [idx]: !Boolean(prev[idx]),
                                }))
                              }
                              style={{ cursor: 'pointer' }}
                              className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-2"
                            >
                              <div className="text-sm">
                                {dict.screening.aiSuggests}{' '}
                                <span
                                  className={
                                    'ml-1 text-sm font-medium ' +
                                    (String(aiData.selected ?? '')
                                      .toLowerCase()
                                      .includes('(exclude)')
                                      ? 'text-red-600'
                                      : 'text-emerald-600')
                                  }
                                >
                                  {aiData.selected ?? dict.screening.noSelection}
                                </span>
                              </div>
                              <div className="text-xs text-gray-500">
                                {panelOpen[idx] ? dict.screening.minimize : dict.screening.maximize}
                              </div>
                            </div>

                            {panelOpen[idx] ? (
                              <div className="mt-2 rounded-md border border-gray-100 bg-white p-3 text-sm whitespace-pre-wrap text-gray-800">
                                <div className="mt-2">
                                  <strong>{dict.screening.confidence}</strong>{' '}
                                  {String(aiData.confidence ?? '')}
                                </div>
                                <div className="mt-2">
                                  <strong>{dict.screening.explanation}</strong>
                                  <div className="mt-1 text-sm text-gray-700">
                                    {aiData.explanation ??
                                      aiData.llm_raw ??
                                      dict.screening.noExplanation}
                                  </div>
                                </div>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Validation checkbox at the bottom of selection area */}
              <div className="mt-4 rounded-md border border-gray-100 bg-gray-50 p-3">
                <label className="flex items-center gap-2 text-sm text-gray-800">
                  <input
                    type="checkbox"
                    checked={l1Checked}
                    disabled={validating}
                    onChange={async (e) => {
                      if (!srId || !citationId) return
                      setValidating(true)
                      try {
                        const headers = {
                          'Content-Type': 'application/json',
                          ...getAuthHeaders(),
                        }
                        await fetch('/api/can-sr/screen/validate', {
                          method: 'POST',
                          headers,
                          body: JSON.stringify({
                            sr_id: srId,
                            citation_id: Number(citationId),
                            step: 'l1',
                            checked: Boolean(e.target.checked),
                          }),
                        })
                        await fetchCitationById(String(citationId))
                      } finally {
                        setValidating(false)
                      }
                    }}
                  />
                  <span>
                    Validated by{' '}
                    <span className="font-medium">
                      {String(userEmail || '—')}
                    </span>
                  </span>
                </label>

                {l1ValidationsSorted.length ? (
                  <div className="mt-2 space-y-1">
                    {l1ValidationsSorted.map((v, idx) => (
                      <div key={`${v.user}-${idx}`} className="text-xs text-gray-600">
                        Validated on {formatValidationDate(v.validated_at)} by {v.user}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </aside>
        </div>
        <div className="mt-6 flex justify-between">
          <button
            onClick={async () => {
              if (!citationId || !srId) return
              const cur = Number(citationId)
              if (Number.isNaN(cur)) return
              const idx = citationIdList.indexOf(cur)
              if (idx <= 0) return
              const target = String(citationIdList[idx - 1])
              // proactively fetch and reset selection state so UI updates immediately
              setSelections({})
              setAiPanels({})
              setPanelOpen({})
              await fetchCitationById(target)
              router.push(
                `/${lang}/can-sr/l1-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                  target,
                )}&threshold=${encodeURIComponent(String(threshold))}`,
              )
            }}
            className="rounded-md border bg-white px-4 py-2 text-sm shadow-sm hover:bg-gray-50"
          >
            {dict.screening.previousCitation}
          </button>
          <button
            onClick={async () => {
              if (!citationId || !srId) return
              const cur = Number(citationId)
              if (Number.isNaN(cur)) return
              const idx = citationIdList.indexOf(cur)
              if (idx === -1 || idx >= citationIdList.length - 1) return
              const target = String(citationIdList[idx + 1])
              // proactively fetch and reset selection state so UI updates immediately
              setSelections({})
              setAiPanels({})
              setPanelOpen({})
              await fetchCitationById(target)
              router.push(
                `/${lang}/can-sr/l1-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                  target,
                )}&threshold=${encodeURIComponent(String(threshold))}`,
              )
            }}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
          >
            {dict.screening.nextCitation}
          </button>
        </div>
      </main>
    </div>
  )
}
