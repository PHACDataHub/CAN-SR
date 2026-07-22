'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { ModelSelector } from '@/components/chat'
import PDFBoundingBoxViewer, { PDFBoundingBoxViewerHandle } from '@/components/can-sr/PDFBoundingBoxViewer'
import { Wand2 } from 'lucide-react'
import { getAuthToken, getTokenType } from '@/lib/auth'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'
import { needsHumanReviewForCriterion } from '@/components/can-sr/needsHumanReview'

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

function extractXmlTag(text: string, tag: string): string {
  if (!text) return ''
  const re = new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, 'i')
  const m = text.match(re)
  return m && m[1] ? String(m[1]).trim() : ''
}

function parseObject(value: any): Record<string, any> | null {
  if (!value) return null
  if (typeof value === 'object') return value
  if (typeof value !== 'string') return null
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

/*
  Full-text single-citation viewer for L2 screening.

  Responsibilities implemented here:
  - Load citation by citation_id via frontend proxy (/api/can-sr/citations/get)
  - Load parsed L2 criteria via frontend proxy (/api/can-sr/reviews/create?sr_id=...&criteria_parsed=1)
  - Render a workspace (left) that shows the full-text PDF viewer with support for sentence-index scrolling
  - Render a selection sidebar (right) with one section per L2 question:
      - Dropdown containing options from criteriaData.possible_answers
      - Default selection set to AI answer from the citation row (column name computed via snake_case_column)
      - "AI" button that calls the backend classify endpoint with screening_step='l2' and updates the AI panel
  - If an AI answer exists for that question, show a collapsible panel containing the parsed LLM JSON
    including confidence, explanation, and evidence_sentences chips that scroll the PDF to the sentence.
  - Persist human selections via the human_classify endpoint with screening_step='l2'
  - Ensure fulltext exists by triggering extraction if missing and then refetching row (grobid-backed)
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

/* Types */
type CriteriaData = {
  questions: string[]
  possible_answers: string[][]
  additional_infos?: (string | null)[] // optional per-question extra guidance when available
}

type LatestAgentRun = {
  citation_id: number
  criterion_key: string
  stage: 'screening' | 'critical' | string
  answer?: string | null
  confidence?: number | null
  rationale?: string | null
  created_at?: string
  guardrails?: any
}

/* Main page component */
export default function CanSrL2ScreenViewPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const citationId = searchParams?.get('citation_id')
  const filterMode = searchParams?.get('filter') || 'all'
  // Get current language to keep language when navigating (must be unconditional hook call)
  const { lang } = useParams<{ lang: string }>()
  const [selectedModel, setSelectedModel] = useState('')
  const dict = useDictionary()

  // Data states
  const [citation, setCitation] = useState<Record<string, any> | null>(null)
  const [criteriaData, setCriteriaData] = useState<CriteriaData | null>(null)
  const [loadingCitation, setLoadingCitation] = useState(false)
  const [loadingCriteria, setLoadingCriteria] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Navigation list (must follow filtered list, not numeric id)
  const [citationIdList, setCitationIdList] = useState<number[]>([])

  // Autosave indicator per question
  const [saveStatus, setSaveStatus] = useState<Record<number, 'idle' | 'saving' | 'saved' | 'error'>>({})

  // UI state: human selections keyed by question index
  const [selections, setSelections] = useState<Record<number, string>>({})
  // AI panel state: parsed llm JSON per question index
  const [aiPanels, setAiPanels] = useState<Record<number, any>>({})
  // Collapsible open state for LLM panels
  const [panelOpen, setPanelOpen] = useState<Record<number, boolean>>({})
  // Source flags for merged criteria: 'l1' or 'l2' per question index
  const [sourceFlags, setSourceFlags] = useState<string[]>([])
  // Hint text from Title/Abstract screening for L1 questions
  const [hintByIndex, setHintByIndex] = useState<Record<number, string>>({})

  // Agentic runs (screening_agent_runs) for this citation
  const [agentRuns, setAgentRuns] = useState<LatestAgentRun[]>([])
  const [titleAbstractRuns, setTitleAbstractRuns] = useState<LatestAgentRun[]>([])
  const [, setLoadingRuns] = useState(false)

  // Per-criterion thresholds for this SR/step
  const [thresholdByCriterionKey, setThresholdByCriterionKey] = useState<Record<string, number> | null>(null)
  const [validating, setValidating] = useState(false)
  const [userEmail, setUserEmail] = useState<string | null>(null)

  // Per-criterion AI status (keyed by question index)
  const [criterionStatus, setCriterionStatus] = useState<Record<number, 'idle' | 'queued' | 'running' | 'done' | 'error'>>({})
  // Run-all progress
  const [runAllProgress, setRunAllProgress] = useState<{ done: number; total: number } | null>(null)
  const [runningAll, setRunningAll] = useState(false)
  const [runAllError, setRunAllError] = useState<string | null>(null)
  const citationKey = `${srId || ''}:${citationId || ''}`
  const currentCitationKeyRef = useRef(citationKey)
  currentCitationKeyRef.current = citationKey

  const l2Validations = useMemo(() => parseValidations((citation as any)?.l2_validations), [citation])
  const l2Checked = useMemo(() => {
    const me = String(userEmail || '')
    if (!me) return false
    return l2Validations.some((v) => v.user === me)
  }, [l2Validations, userEmail])
  const l2ValidationsSorted = useMemo(() => {
    return [...l2Validations].sort((a, b) => String(b.validated_at || '').localeCompare(String(a.validated_at || '')))
  }, [l2Validations])

  // Fulltext PDF viewer linkage
  const [fulltextCoords, setFulltextCoords] = useState<any[] | null>(null)
  const [fulltextPages, setFulltextPages] = useState<{ width: number; height: number }[] | null>(null)
  const [fulltextStr, setFulltextStr] = useState<string | null>(null)
  const viewerRef = useRef<PDFBoundingBoxViewerHandle | null>(null)

  useEffect(() => {
    if (!srId || !citationId) {
      router.replace('/can-sr')
      return
    }
  }, [srId, citationId, router])

  // Load thresholds for this SR (saved thresholds)
  useEffect(() => {
    if (!srId) return
    const load = async () => {
      try {
        const headers = getAuthHeaders()
        const res = await fetch(
          `/api/can-sr/reviews/thresholds?sr_id=${encodeURIComponent(srId)}`,
          { method: 'GET', headers },
        )
        const j = await res.json().catch(() => ({}))
        const t = res.ok ? j?.screening_thresholds : null
        const stepMap = t && typeof t === 'object' ? (t as any).l2 : null
        setThresholdByCriterionKey(stepMap && typeof stepMap === 'object' ? stepMap : {})
      } catch {
        setThresholdByCriterionKey({})
      }
    }
    load()
  }, [srId])

  // Load filtered citation ids for navigation (L2 is filtered by L1 pass)
  useEffect(() => {
    if (!srId) return
    const loadIds = async () => {
      try {
        const headers = getAuthHeaders()
        const res = await fetch(
          `/api/can-sr/screen/citation-ids?sr_id=${encodeURIComponent(srId)}&step=l2&filter=${encodeURIComponent(
            filterMode,
          )}`,
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
  }, [srId, filterMode])

  const navSessionKey = useMemo(() => {
    if (!srId) return null
    return `navProgress:${srId}:l2:${filterMode}`
  }, [srId, filterMode])

  const progressInfo = useMemo(() => {
    const cur = Number(citationId)
    const idx = Number.isFinite(cur) ? citationIdList.indexOf(cur) : -1
    const total = citationIdList.length
    let startedAt = idx
    try {
      if (navSessionKey) {
        const raw = window.sessionStorage.getItem(navSessionKey)
        const parsed = raw ? JSON.parse(raw) : null
        if (parsed && typeof parsed.startIndex === 'number') startedAt = parsed.startIndex
        if (!raw && idx >= 0) {
          window.sessionStorage.setItem(navSessionKey, JSON.stringify({ startIndex: idx, startedAt: Date.now() }))
          startedAt = idx
        }
      }
    } catch {
      // ignore
    }
    return { idx, total, startedAt }
  }, [citationId, citationIdList, navSessionKey])

  // Fetch current user email for validation toggling.
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

  // Load citation row (and ensure fulltext is extracted if missing)
  const fetchCitationById = useCallback(async (id: string, signal?: AbortSignal) => {
    if (!srId || !id) return
    const requestKey = `${srId}:${id}`
    setLoadingCitation(true)
    try {
      const headers = getAuthHeaders()
      const res = await fetch(
        `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
        { method: 'GET', headers, signal },
      )
      const data = await res.json().catch(() => ({}))
      if (currentCitationKeyRef.current !== requestKey) return
      if (!res.ok) {
        setError(
          data?.error || data?.detail || `Failed to load citation (${res.status})`,
        )
        setCitation(null)
      } else {
        setCitation(data || null)

        // Extract overlay data
        const parseJson = (v: any) => {
          if (!v) return null
          try {
            return typeof v === 'string' ? JSON.parse(v) : v
          } catch {
            return null
          }
        }

        const ft = typeof (data as any).fulltext === 'string' ? (data as any).fulltext : null
        setFulltextStr(ft)
        const coordsAny = parseJson((data as any).fulltext_coords) ?? (data as any).fulltext_coords
        setFulltextCoords(Array.isArray(coordsAny) ? coordsAny : null)
        const pagesAny = parseJson((data as any).fulltext_pages) ?? (data as any).fulltext_pages
        setFulltextPages(Array.isArray(pagesAny) ? pagesAny : null)

        // If coords/pages missing, trigger backend extraction then refetch row
        const needExtract =
          !Array.isArray(coordsAny) || coordsAny.length === 0 || !Array.isArray(pagesAny) || pagesAny.length === 0
        if (needExtract) {
          try {
            const res2 = await fetch(
              `/api/can-sr/citations/full-text?action=extract&sr_id=${encodeURIComponent(
                srId || '',
              )}&citation_id=${encodeURIComponent(String(id || ''))}`,
              { method: 'POST', headers, signal },
            )
            if (res2.ok && currentCitationKeyRef.current === requestKey) {
              const res3 = await fetch(
                `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                  String(id),
                )}`,
                { headers, signal },
              )
              const row2 = await res3.json().catch(() => ({}))
              if (currentCitationKeyRef.current !== requestKey) return
              if (res3.ok) setCitation(row2 || null)

              const ft2 = typeof (row2 as any).fulltext === 'string' ? (row2 as any).fulltext : null
              setFulltextStr(ft2)

              const coordsAny2 = parseJson((row2 as any).fulltext_coords) ?? (row2 as any).fulltext_coords
              setFulltextCoords(Array.isArray(coordsAny2) ? coordsAny2 : null)

              const pagesAny2 = parseJson((row2 as any).fulltext_pages) ?? (row2 as any).fulltext_pages
              setFulltextPages(Array.isArray(pagesAny2) ? pagesAny2 : null)
            }
          } catch (err: any) {
            if (err?.name === 'AbortError' || currentCitationKeyRef.current !== requestKey) return
            console.warn('Failed to extract fulltext for overlay', err)
          }
        }
      }
    } catch (err: any) {
      if (err?.name === 'AbortError' || currentCitationKeyRef.current !== requestKey) return
      console.error('Citation fetch error', err)
      setError(err?.message || 'Network error while fetching citation')
    } finally {
      if (currentCitationKeyRef.current === requestKey) setLoadingCitation(false)
    }
  }, [srId])

  useEffect(() => {
    if (!srId || !citationId) return
    const controller = new AbortController()
    setCitation(null)
    setError(null)
    setSelections({})
    setAiPanels({})
    setPanelOpen({})
    setHintByIndex({})
    setAgentRuns([])
    setTitleAbstractRuns([])
    setSaveStatus({})
    setCriterionStatus({})
    setRunAllProgress(null)
    setRunAllError(null)
    setRunningAll(false)
    setFulltextStr(null)
    setFulltextCoords(null)
    setFulltextPages(null)
    void fetchCitationById(citationId, controller.signal)
    return () => controller.abort()
  }, [citationId, fetchCitationById, srId])

  // Re-usable loader so we can refresh after triggering an agentic run.
  async function loadRuns(context?: { srId: string; citationId: string }) {
    const runContext = context || (srId && citationId ? { srId, citationId } : null)
    if (!runContext) return
    const requestKey = `${runContext.srId}:${runContext.citationId}`
    setLoadingRuns(true)
    try {
      const headers = getAuthHeaders()
      const res = await fetch(
        `/api/can-sr/screen/agent-runs/latest?sr_id=${encodeURIComponent(
          runContext.srId,
        )}&pipeline=${encodeURIComponent('fulltext')}&citation_ids=${encodeURIComponent(
          runContext.citationId,
        )}`,
        { method: 'GET', headers },
      )
      const data = await res.json().catch(() => ({}))
      if (currentCitationKeyRef.current !== requestKey) return
      if (res.ok && Array.isArray(data?.runs)) {
        setAgentRuns(data.runs as LatestAgentRun[])
      } else {
        setAgentRuns([])
      }
    } catch {
      if (currentCitationKeyRef.current !== requestKey) return
      setAgentRuns([])
    } finally {
      if (currentCitationKeyRef.current === requestKey) setLoadingRuns(false)
    }
  }

  // Load latest agent runs for this citation (screening + critical per criterion)
  useEffect(() => {
    if (!srId || !citationId) return
    void loadRuns()
    const requestKey = `${srId}:${citationId}`
    void (async () => {
      try {
        const res = await fetch(
          `/api/can-sr/screen/agent-runs/latest?sr_id=${encodeURIComponent(srId)}&pipeline=title_abstract&citation_ids=${encodeURIComponent(citationId)}`,
          { method: 'GET', headers: getAuthHeaders() },
        )
        const data = await res.json().catch(() => ({}))
        if (currentCitationKeyRef.current !== requestKey) return
        setTitleAbstractRuns(res.ok && Array.isArray(data?.runs) ? data.runs : [])
      } catch {
        if (currentCitationKeyRef.current === requestKey) setTitleAbstractRuns([])
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const titleAbstractRunsByCriterion = useMemo(() => {
    const by: Record<string, LatestAgentRun> = {}
    for (const run of titleAbstractRuns) {
      if (String(run?.stage || '') !== 'screening') continue
      const key = String(run?.criterion_key || '')
      if (key) by[key] = run
    }
    return by
  }, [titleAbstractRuns])

  // Load parsed criteria (L1 + L2 merged, L1 first)
  useEffect(() => {
    if (!srId) return
    const load = async () => {
      setLoadingCriteria(true)
      try {
        const headers = getAuthHeaders()
        const res = await fetch(
          `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}&criteria_parsed=1`,
          { method: 'GET', headers },
        )
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          console.warn('Failed to load criteria', data)
          setCriteriaData(null)
          setSourceFlags([])
        } else {
          const parsed = data?.criteria_parsed || data?.criteria || {}

          const parseBlock = (block: any) => {
            if (!block) {
              return { questions: [], possible_answers: [], additional_infos: [] as (string | null)[] }
            }
            if (!Array.isArray(block?.questions)) {
              // mapping form: { question: { option: description } }
              try {
                const qArr: string[] = []
                const ansArr: string[][] = []
                const addInfos: (string | null)[] = []
                Object.keys(block || {}).forEach((q) => {
                  qArr.push(q)
                  const optionsMap = block[q] || {}
                  const entries = Object.entries(optionsMap || {})
                  const opts: string[] = entries.map(([opt]) => opt)
                  ansArr.push(opts)
                  const guidanceParts = entries.map(([opt, desc]) => {
                    let d: any = desc
                    if (typeof d === 'string') {
                      // keep
                    } else if (Array.isArray(d)) {
                      d = d.join(' ')
                    } else if (d != null) {
                      d = String(d)
                    } else {
                      d = ''
                    }
                    const clean = String(d).replace(/\s+/g, ' ').trim()
                    return `- ${opt}: ${clean}`
                  })
                  addInfos.push(guidanceParts.length ? guidanceParts.join('\n') : null)
                })
                return { questions: qArr, possible_answers: ansArr, additional_infos: addInfos }
              } catch {
                const questions = block?.questions || []
                const possible_answers = block?.possible_answers || []
                const additional_infos = block?.additional_infos || []
                return {
                  questions: Array.isArray(questions) ? questions : [],
                  possible_answers: Array.isArray(possible_answers) ? possible_answers : [],
                  additional_infos: Array.isArray(additional_infos) ? additional_infos : [],
                }
              }
            } else {
              const questions = block?.questions || []
              const possible_answers = block?.possible_answers || []
              const additional_infos = block?.additional_infos || []
              return {
                questions: Array.isArray(questions) ? questions : [],
                possible_answers: Array.isArray(possible_answers) ? possible_answers : [],
                additional_infos: Array.isArray(additional_infos) ? additional_infos : [],
              }
            }
          }

          const l1Block = parsed?.l1 ?? parsed?.criteria ?? null
          const l2Block = parsed?.l2 ?? parsed?.l2_criteria ?? null

          const l1Parsed = parseBlock(l1Block)
          const l2Parsed = parseBlock(l2Block)

          const mergedQuestions = [...l1Parsed.questions, ...l2Parsed.questions]
          const mergedAnswers = [...l1Parsed.possible_answers, ...l2Parsed.possible_answers]
          const mergedInfos = [...l1Parsed.additional_infos, ...l2Parsed.additional_infos]

          setCriteriaData({
            questions: mergedQuestions,
            possible_answers: mergedAnswers,
            additional_infos: mergedInfos,
          })
          setSourceFlags([
            ...l1Parsed.questions.map(() => 'l1'),
            ...l2Parsed.questions.map(() => 'l2'),
          ])
        }
      } catch (err) {
        console.error('Criteria fetch error', err)
        setCriteriaData(null)
        setSourceFlags([])
      } finally {
        setLoadingCriteria(false)
      }
    }
    load()
  }, [srId])

  // When citation + criteria are loaded, initialize selection defaults from AI columns and build L1 hints
  useEffect(() => {
    if (!citation || !criteriaData) return

    const newSelections: Record<number, string> = {}
    const newAiPanels: Record<number, any> = {}
    const newPanelOpen: Record<number, boolean> = {}
    const newHints: Record<number, string> = {}

    criteriaData.questions.forEach((q: string, idx: number) => {
      const llmCol = snakeCaseColumn(q)
      const humanCol = humanScreenColumn(q)
      const criterionKey = llmCol.replace(/^llm_/, '')
      const fulltextRun = runsByCriterion[criterionKey]?.screening
      const titleAbstractRun = titleAbstractRunsByCriterion[criterionKey]
      const citationFulltextMd5 = String((citation as any)?.fulltext_md5 || '')
      const runGuardrails = parseObject(fulltextRun?.guardrails)
      const runFulltextMd5 = String(runGuardrails?.fulltext_md5 || '')
      const isCurrentFulltextRun = Boolean(
        fulltextRun && citationFulltextMd5 && runFulltextMd5 === citationFulltextMd5,
      )

      const humanRaw = (citation as any)?.[humanCol]
      const llmRaw = (citation as any)?.[llmCol]

      // Parse possible JSON payloads from DB
      let humanParsed = humanRaw
      if (typeof humanRaw === 'string') {
        try {
          humanParsed = JSON.parse(humanRaw)
        } catch {
          humanParsed = humanRaw
        }
      }
      let llmParsed = llmRaw
      if (typeof llmRaw === 'string') {
        try {
          llmParsed = JSON.parse(llmRaw)
        } catch {
          llmParsed = llmRaw
        }
      }

      // human_* is historically shared by L1 and L2. Only accept values that
      // explicitly identify themselves as Full Text/L2; an untagged legacy value
      // is ambiguous and must not appear as a previous Full Text review.
      const isFulltextHuman = humanParsed && typeof humanParsed === 'object' && (
        (humanParsed as any).pipeline === 'fulltext' ||
        String((humanParsed as any).screening_step || '').toLowerCase() === 'l2'
      )
      if (isFulltextHuman && (humanParsed as any).selected !== undefined) {
        newSelections[idx] = (humanParsed as any).selected
      }

      // 2) For L1 questions: show hint from prior L1 screening (llm_*), but do not prefill from it
      if (sourceFlags[idx] === 'l1') {
        // The shared llm_* column may have been overwritten by either pipeline.
        // Use the pipeline-specific run so a full-text result cannot masquerade
        // as the earlier Title/Abstract answer (or vice versa).
        if (titleAbstractRun?.answer != null) newHints[idx] = String(titleAbstractRun.answer)
      }

      // A Full Text AI panel must only exist when there is a persisted fulltext
      // screening run. Never display a shared/legacy L1 llm_* value as L2 output.
      if (fulltextRun && isCurrentFulltextRun) {
        const llmMatchesFulltext = llmParsed && typeof llmParsed === 'object' &&
          String((llmParsed as any).selected ?? '') === String(fulltextRun.answer ?? '') &&
          ((llmParsed as any).pipeline === 'fulltext' || !(llmParsed as any).pipeline)
        newAiPanels[idx] = {
          ...(llmMatchesFulltext ? llmParsed : {}),
          selected: fulltextRun.answer ?? '',
          confidence: fulltextRun.confidence,
          explanation: fulltextRun.rationale ?? '',
          pipeline: 'fulltext',
        }
        newPanelOpen[idx] = false
      }

      // For L2 questions: if no human selection present, allow llm_* to prefill the dropdown
      const hasSelection = newSelections[idx] !== undefined && newSelections[idx] !== ''
      if (sourceFlags[idx] === 'l2' && !hasSelection) {
        const aiSelected = (newAiPanels[idx] && typeof newAiPanels[idx].selected === 'string') ? newAiPanels[idx].selected : null
        if (aiSelected) {
          newSelections[idx] = aiSelected
        }
      }
    })

    setSelections(newSelections)
    setAiPanels(newAiPanels)
    setPanelOpen(newPanelOpen)
    setHintByIndex(newHints)
  }, [citation, criteriaData, sourceFlags, runsByCriterion, titleAbstractRunsByCriterion])

  // Persist human classification
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
        screening_step: 'l2',
      }
      const res = await fetch(
        `/api/can-sr/screen?action=human_classify&sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
          String(citationId),
        )}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify(payload),
        },
      )
      await res.json().catch(() => ({}))
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

    // Persist human selection in background
    if (!criteriaData) return
    const question = criteriaData.questions[questionIndex]
    const ok = await postHumanClassifyPayload(question, value)
    setSaveStatus((prev) => ({ ...prev, [questionIndex]: ok ? 'saved' : 'error' }))
  }

  // Run agentic fulltext screening for a single criterion (per-question AI button)
  async function classifyQuestion(
    questionIndex: number,
    context?: { srId: string; citationId: string; questions: string[]; model: string },
  ): Promise<boolean> {
    const runContext = context || (srId && citationId && criteriaData
      ? { srId, citationId, questions: criteriaData.questions, model: selectedModel }
      : null)
    if (!runContext) return false
    const requestKey = `${runContext.srId}:${runContext.citationId}`
    if (currentCitationKeyRef.current !== requestKey) return false
    const q = runContext.questions[questionIndex]
    if (!q) return false
    setRunAllError(null)
    const ck = q.trim().toLowerCase().replace(/[^\w]+/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '').slice(0, 56)
    setCriterionStatus((prev) => ({ ...prev, [questionIndex]: 'running' }))
    try {
      const headers = { 'Content-Type': 'application/json', ...getAuthHeaders() }
      const res = await fetch('/api/can-sr/screen/fulltext/run', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          sr_id: runContext.srId,
          citation_id: Number(runContext.citationId),
          model: runContext.model,
          temperature: 0.0,
          max_tokens: 2000,
          prompt_version: 'v1',
          criterion_key: ck,
        }),
      })
      const runData = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(runData?.detail || runData?.error || `AI request failed (${res.status})`)
      if (String(runData?.citation_id ?? runContext.citationId) !== runContext.citationId) {
        throw new Error('AI response did not match the requested citation')
      }
      if (currentCitationKeyRef.current !== requestKey) return false

      // Targeted update: fetch only the llm_* column for this criterion and update
      // aiPanels directly — avoids re-rendering the PDF viewer (no setCitation call).
      try {
        const llmColName = `llm_${ck}`
        const citRes = await fetch(
          `/api/can-sr/citations/get?sr_id=${encodeURIComponent(runContext.srId)}&citation_id=${encodeURIComponent(runContext.citationId)}`,
          { method: 'GET', headers: getAuthHeaders() },
        )
        const citData = await citRes.json().catch(() => ({}))
        if (currentCitationKeyRef.current === requestKey && citRes.ok && citData) {
          const llmRaw = citData[llmColName]
          let llmParsed = llmRaw
          if (typeof llmRaw === 'string') {
            try { llmParsed = JSON.parse(llmRaw) } catch { llmParsed = llmRaw }
          }
          if (llmParsed && typeof llmParsed === 'object') {
            setAiPanels((prev) => ({ ...prev, [questionIndex]: llmParsed }))
          }
        }
      } catch { /* best-effort */ }

      // Refresh agent runs (no PDF state changes)
      await loadRuns({ srId: runContext.srId, citationId: runContext.citationId })
      if (currentCitationKeyRef.current !== requestKey) return false
      setCriterionStatus((prev) => ({ ...prev, [questionIndex]: 'done' }))
      return true
    } catch (err) {
      console.error('Classify API error', err)
      if (currentCitationKeyRef.current === requestKey) {
        setCriterionStatus((prev) => ({ ...prev, [questionIndex]: 'error' }))
        setRunAllError(err instanceof Error ? err.message : 'Full Text AI failed')
      }
      return false
    }
  }

  // Run all criteria sequentially (Run All AI button)
  async function runAllAI() {
    if (!srId || !citationId || !criteriaData || runningAll) return
    const context = { srId, citationId, questions: [...criteriaData.questions], model: selectedModel }
    const requestKey = `${srId}:${citationId}`
    const total = context.questions.length
    setRunningAll(true)
    setRunAllProgress({ done: 0, total })
    setRunAllError(null)
    setCriterionStatus(Object.fromEntries(context.questions.map((_, index) => [index, 'queued'])))
    try {
      const failures: number[] = []
      for (let index = 0; index < context.questions.length; index++) {
        if (currentCitationKeyRef.current !== requestKey) break
        const ok = await classifyQuestion(index, context)
        if (!ok) failures.push(index)
        if (currentCitationKeyRef.current !== requestKey) break
        setRunAllProgress({ done: index + 1, total })
      }
      if (failures.length) {
        setRunAllError(`${failures.length} of ${total} questions failed.`)
      }
    } finally {
      if (currentCitationKeyRef.current === requestKey) setRunningAll(false)
    }
  }

  async function onRunAllAI() {
    try {
      await runAllAI()
    } catch (err: any) {
      console.error('Run All AI error', err)
      setRunAllError(err?.message || 'Run All AI failed')
      setCriterionStatus((prev) => Object.fromEntries(Object.keys(prev).map((key) => [Number(key), 'error'])))
    }
  }

  // Render workspace: PDF viewer with overlay
  const panelsKeyed = useMemo(() => {
    const mappedPanels: Record<string, any> = {}
    const mappedOpen: Record<string, boolean> = {}
    if (criteriaData && Array.isArray(criteriaData.questions)) {
      criteriaData.questions.forEach((q, i) => {
        const key = `Q${i}_${String(q).replace(/\s+/g, ' ').trim().slice(0, 48)}`
        if (aiPanels[i]) mappedPanels[key] = aiPanels[i]
        mappedOpen[key] = !!panelOpen[i]
      })
    }
    return { panels: mappedPanels, open: mappedOpen }
  }, [criteriaData, aiPanels, panelOpen])

  // Helpers for table/figure evidence -> viewer highlight
  const parsedTables = useMemo(() => {
    if (!citation) return [] as any[]
    let v: any = (citation as any).fulltext_tables
    if (!v) return []
    try {
      if (typeof v === 'string') v = JSON.parse(v)
    } catch {
      // ignore
    }
    return Array.isArray(v) ? v : []
  }, [citation])

  const parsedFigures = useMemo(() => {
    if (!citation) return [] as any[]
    let v: any = (citation as any).fulltext_figures
    if (!v) return []
    try {
      if (typeof v === 'string') v = JSON.parse(v)
    } catch {
      // ignore
    }
    return Array.isArray(v) ? v : []
  }, [citation])

  const scrollToArtifact = (kind: 'table' | 'figure', idx: number) => {
    const list = kind === 'table' ? parsedTables : parsedFigures
    const item = list.find((x: any) => Number(x?.index) === Number(idx))
    console.log('[artifact-click]', { kind, idx, hasViewer: !!viewerRef.current, item })
    if (!item || !viewerRef.current) return
    const bbox = item?.bounding_box
    // We store normalized boxes as an array of {page,x,y,width,height}
    const first = Array.isArray(bbox) ? bbox[0] : null
    console.log('[artifact-bbox]', { kind, idx, bbox, first })
    if (!first) return
    viewerRef.current.scrollToCoord(first)
  }

  const workspace = useMemo(() => {
    if (error)
      return <div className="text-sm text-red-600">{error}</div>
    if (loadingCitation)
      return <div className="text-sm text-gray-600">{dict.screening.loadingCitation}</div>
    if (!citation)
      return <div className="text-sm text-gray-600">{dict.screening.citationNotFound}</div>

    return (
      <PDFBoundingBoxViewer
        srId={srId || ''}
        citationId={citationId ?? ''}
        conversionId={null}
        fileName={"Fulltext"}
        coords={fulltextCoords || []}
        pages={fulltextPages || []}
        aiPanels={panelsKeyed.panels}
        panelOpen={panelsKeyed.open}
        fulltext={fulltextStr || ''}
        defaultFitToWidth={true}
        ref={viewerRef}
      />
    )
  }, [citation, loadingCitation, srId, citationId, fulltextCoords, fulltextPages, fulltextStr, panelsKeyed, dict, error])

  if (!srId || !citationId) {
    // guard - redirect already handled in effect but keep safe render
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title={dict.screening.fullText}
        backHref={`/can-sr/l2-screen?sr_id=${encodeURIComponent(srId || '')}&filter=${encodeURIComponent(filterMode)}`}
        backLabel={dict.cansr.backToCitations}
        right={
          <ModelSelector
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        }
      />

      <main className="mx-auto max-w-8xl px-3 py-3">

        {/* Filter/session progress bar */}
        {progressInfo.total > 0 && progressInfo.idx >= 0 ? (
          <div className="mb-3 rounded-md border border-gray-200 bg-white p-3">
            <div className="flex items-center justify-between text-xs text-gray-600">
              <div>
                Progress: <span className="font-medium">{progressInfo.idx + 1}</span> / {progressInfo.total}
              </div>
              <div>
                Since start: <span className="font-medium">{Math.max(0, progressInfo.idx - progressInfo.startedAt + 1)}</span>
              </div>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded bg-gray-200">
              <div
                className="h-2 bg-emerald-600"
                style={{ width: `${Math.min(100, ((progressInfo.idx + 1) / progressInfo.total) * 100)}%` }}
              />
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-12 gap-3">
          {/* Workspace (left) */}
          <div className="col-span-9">
              {workspace}
          </div>

          {/* Selection sidebar (right) */}
          <aside className="col-span-3">
            <div className="h-full space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm flex flex-col">
              <div>
                <h4 className="text-xl font-semibold text-gray-900 text-center">{dict.screening.screeningQuestions}</h4>
              </div>

              {/* Run All AI button */}
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-gray-500">
                  {runAllProgress ? `${runAllProgress.done}/${runAllProgress.total} criteria` : ''}
                </span>
                <button
                  onClick={onRunAllAI}
                  disabled={runningAll || !criteriaData || criteriaData.questions.length === 0 || !(citation as any)?.fulltext_md5}
                  className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {runningAll ? (
                    <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                  ) : (
                    <Wand2 className="h-3 w-3" />
                  )}
                  {runAllProgress
                    ? `${runAllProgress.done}/${runAllProgress.total}`
                    : 'Run All AI'}
                </button>
              </div>
              {runAllError ? <div className="text-xs text-red-600">{runAllError}</div> : null}

              {loadingCriteria ? (
                <div className="text-sm text-gray-600">{dict.screening.loadingCriteria}</div>
              ) : !criteriaData || criteriaData.questions.length === 0 ? (
                <div className="text-sm text-gray-600">
                  {dict.screening.noL2Criteria}
                </div>
              ) : (
                <div className="rounded-md border border-gray-100 p-3 h-[680px] overflow-y-auto">
                  <div className="space-y-4">
                  {criteriaData.questions.map((q, idx) => {
                    const options = criteriaData.possible_answers[idx] || []
                    const current = selections[idx] ?? ''
                    const aiData = aiPanels[idx]
                    const aiSelected =
                      aiData && aiData.selected ? aiData.selected : undefined

                    // Per-question highlight aligned with list/back-end logic.
                    // - Highlight when this criterion triggers review (low confidence OR critical disagreement OR guardrail issue)
                    // - BUT do not highlight if this criterion is a confident-exclude (exclude + conf>=thr + critical agrees)
                    const criterionKey = q
                      ? q
                          .trim()
                          .toLowerCase()
                          .replace(/[^\w]+/g, '_')
                          .replace(/_+/g, '_')
                          .replace(/^_+|_+$/g, '')
                          .slice(0, 56)
                      : ''

                    const r = (runsByCriterion as any)?.[criterionKey] || {}
                    const currentPdfMd5 = String((citation as any)?.fulltext_md5 || '')
                    const runMatchesCurrentPdf = (run: any) => {
                      const guardrails = parseObject(run?.guardrails)
                      return Boolean(run && currentPdfMd5 && String(guardrails?.fulltext_md5 || '') === currentPdfMd5)
                    }
                    const scr = runMatchesCurrentPdf(r.screening) ? r.screening : undefined
                    const crit = runMatchesCurrentPdf(r.critical) ? r.critical : undefined
                    const perThrRaw = thresholdByCriterionKey ? Number((thresholdByCriterionKey as any)[criterionKey]) : NaN
                    const thr = Number.isFinite(perThrRaw) ? Math.max(0, Math.min(1, perThrRaw)) : 0.9

                    const { needsHuman, criticalDisagrees: critDisagrees } = needsHumanReviewForCriterion({
                      threshold: thr,
                      screening: scr,
                      critical: crit,
                    })
                    const hasAgentic = !!scr || !!crit

                    // Prefer agentic screening run when available to avoid mismatches
                    const displayConfidence =
                      Number.isFinite(Number((scr as any)?.confidence))
                        ? Number((scr as any)?.confidence)
                        : Number(aiData?.confidence)

                    const aiExpl =
                      (typeof (aiData as any)?.explanation === 'string' ? String((aiData as any).explanation) : '') ||
                      (typeof (aiData as any)?.rationale === 'string' ? String((aiData as any).rationale) : '') ||
                      (typeof (aiData as any)?.llm_raw === 'string' ? String((aiData as any).llm_raw) : '')

                    const scrRationale = typeof (scr as any)?.rationale === 'string' ? String((scr as any).rationale) : ''
                    const displayExplanationRaw = (scrRationale || aiExpl || '').trim()
                    const displayExplanation =
                      extractXmlTag(displayExplanationRaw, 'rationale') || displayExplanationRaw

                    return (
                      <div
                        key={idx}
                        className={
                          'rounded-md border-2 p-3 ' + (needsHuman ? 'border-amber-400' : 'border-gray-100')
                        }
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-800">
                              {q}
                            </p>

                            {sourceFlags[idx] === 'l1' ? (
                              <p className="mt-1 text-xs text-gray-500">
                                {dict.screening.titleAbstractAnswer} {hintByIndex[idx] ?? dict.screening.none}
                              </p>
                            ) : null}

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
                                disabled={criterionStatus[idx] === 'running' || runningAll || !(citation as any)?.fulltext_md5}
                                className="rounded-md border px-2 py-1 text-xs hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                <span className="inline-flex items-center gap-1">
                                  {criterionStatus[idx] === 'running' ? (
                                    <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
                                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                                    </svg>
                                  ) : (
                                    <Wand2 className="h-3 w-3" />
                                  )}
                                  AI
                                </span>
                              </button>

                              {criterionStatus[idx] === 'running' ? (
                                <span className="text-[10px] text-blue-600">Running…</span>
                              ) : criterionStatus[idx] === 'queued' ? (
                                <span className="text-[10px] text-gray-500">Queued</span>
                              ) : criterionStatus[idx] === 'done' ? (
                                <span className="text-[10px] text-emerald-600">Completed</span>
                              ) : criterionStatus[idx] === 'error' ? (
                                <span className="text-[10px] text-red-600">Error</span>
                              ) : saveStatus[idx] === 'saving' ? (
                                <span className="text-[10px] text-gray-500">{dict.common.save}...</span>
                              ) : saveStatus[idx] === 'saved' ? (
                                <span className="text-[10px] text-emerald-600">{dict.common.done}</span>
                              ) : saveStatus[idx] === 'error' ? (
                                <span className="text-[10px] text-red-600">{dict.common.error}</span>
                              ) : null}
                          </div>
                        </div>

                        {/* AI panel: collapsible with evidence chips */}
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
                                  {Number.isFinite(displayConfidence)
                                    ? String(displayConfidence)
                                    : String(aiData.confidence ?? '')}
                                </div>
                                <div className="mt-2">
                                  <strong>{dict.screening.explanation}</strong>
                                  <div className="mt-1 text-sm text-gray-700">
                                    {displayExplanation || dict.screening.noExplanation}
                                  </div>
                                </div>

                                {hasAgentic && crit ? (
                                  <div className="mt-3 rounded-md border border-gray-100 bg-gray-50 p-2 text-xs text-gray-700">
                                    <div className="mt-1 font-semibold text-gray-800">
                                      {critDisagrees ? (
                                        <span className="text-amber-700">
                                          Critical review recommends a different answer: {String((crit as any)?.answer ?? '—')}
                                        </span>
                                      ) : (
                                        <span className="text-emerald-700">Critical review supports the screening answer</span>
                                      )}
                                    </div>
                                    <div>Judgment confidence: {String((crit as any)?.confidence ?? '—')}</div>
                                  </div>
                                ) : null}
                                {Array.isArray(aiData?.evidence_sentences) && aiData.evidence_sentences.length > 0 ? (
                                  <div className="mt-2">
                                    <strong>{dict.screening.evidence}</strong>
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {aiData.evidence_sentences.map((item: any, k: number) => {
                                        const isCoord = item && typeof item === 'object'
                                        const label = isCoord
                                          ? `${dict.screening.page} ${String(item.page ?? item.page_number ?? item.pageNum ?? '?')}${item.text ? `: ${String(item.text).slice(0, 80)}` : ''}`
                                          : `${dict.screening.sentence} ${String(item)}`
                                        const onClick = () => {
                                          if (!viewerRef.current) return
                                          if (isCoord) {
                                            viewerRef.current.scrollToCoord(item)
                                          } else {
                                            const idxNum = Number(item)
                                            if (!Number.isNaN(idxNum)) {
                                              viewerRef.current.scrollToSentenceIndex(idxNum)
                                            }
                                          }
                                        }
                                        return (
                                          <button
                                            key={k}
                                            onClick={onClick}
                                            className="rounded border px-1.5 py-0.5 text-xs hover:bg-gray-50"
                                            title={label}
                                            type="button"
                                          >
                                            {label}
                                          </button>
                                        )
                                      })}
                                    </div>
                                  </div>
                                ) : null}

                                {Array.isArray(aiData?.evidence_tables) && aiData.evidence_tables.length > 0 ? (
                                  <div className="mt-2">
                                    <strong>Evidence tables:</strong>
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {aiData.evidence_tables.map((t: any, k: number) => {
                                        const label = `Table T${String(t)}`
                                        return (
                                          <button
                                            key={k}
                                            type="button"
                                            onClick={() => scrollToArtifact('table', Number(t))}
                                            className="rounded border px-1.5 py-0.5 text-xs text-gray-700 bg-gray-50 hover:bg-gray-100"
                                            title={label}
                                          >
                                            {label}
                                          </button>
                                        )
                                      })}
                                    </div>
                                  </div>
                                ) : null}

                                {Array.isArray(aiData?.evidence_figures) && aiData.evidence_figures.length > 0 ? (
                                  <div className="mt-2">
                                    <strong>Evidence figures:</strong>
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {aiData.evidence_figures.map((f: any, k: number) => {
                                        const label = `Figure F${String(f)}`
                                        return (
                                          <button
                                            key={k}
                                            type="button"
                                            onClick={() => scrollToArtifact('figure', Number(f))}
                                            className="rounded border px-1.5 py-0.5 text-xs text-gray-700 bg-gray-50 hover:bg-gray-100"
                                            title={label}
                                          >
                                            {label}
                                          </button>
                                        )
                                      })}
                                    </div>
                                  </div>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              </div>
              )}
              {/* Validation checkbox — at the bottom, matching L1 screen layout */}
              <div className="mt-2 rounded-md border border-gray-100 bg-gray-50 p-3">
                <label className="flex items-center gap-2 text-sm text-gray-800">
                  <input
                    type="checkbox"
                    checked={l2Checked}
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
                            step: 'l2',
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
                    Validated by <span className="font-medium">{String(userEmail || '—')}</span>
                  </span>
                </label>

                {l2ValidationsSorted.length ? (
                  <div className="mt-2 space-y-1">
                    {l2ValidationsSorted.map((v, idx) => (
                      <div key={`${v.user}-${idx}`} className="text-xs text-gray-600">
                        Validated on {formatValidationDate(v.validated_at)} by {v.user}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-2 text-xs text-gray-600">Not validated</div>
                )}
              </div>

              <div className="flex items-center justify-between mt-4">
                <button
                  disabled={runningAll}
                  onClick={() => {
                    if (!citationId || !srId) return
                    const cur = Number(citationId)
                    if (Number.isNaN(cur)) return
                    const idx = citationIdList.indexOf(cur)
                    if (idx <= 0) return
                    const target = String(citationIdList[idx - 1])
                    router.push(
                      `/${lang}/can-sr/l2-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                        target,
                      )}&filter=${encodeURIComponent(filterMode)}`,
                    )
                  }}
                  className="rounded-md border bg-white px-4 py-2 text-sm shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {dict.screening.previousCitation}
                </button>
                <button
                  disabled={runningAll}
                  onClick={() => {
                    if (!citationId || !srId) return
                    const cur = Number(citationId)
                    if (Number.isNaN(cur)) return
                    const idx = citationIdList.indexOf(cur)
                    if (idx === -1) return
                    if (idx >= citationIdList.length - 1) {
                      router.push(`/${lang}/can-sr/l2-screen?sr_id=${encodeURIComponent(srId)}&filter=${encodeURIComponent(filterMode)}`)
                      return
                    }
                    const target = String(citationIdList[idx + 1])
                    router.push(
                      `/${lang}/can-sr/l2-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                        target,
                      )}&filter=${encodeURIComponent(filterMode)}`,
                    )
                  }}
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {dict.screening.nextCitation}
                </button>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  )
}
