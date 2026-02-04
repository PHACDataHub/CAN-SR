'use client'

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { ModelSelector } from '@/components/chat'
import PDFBoundingBoxViewer, { PDFBoundingBoxViewerHandle } from '@/components/can-sr/PDFBoundingBoxViewer'
import { Wand2 } from 'lucide-react'
import { getAuthToken, getTokenType } from '@/lib/auth'

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

/* Main page component */
export default function CanSrL2ScreenViewPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const citationId = searchParams?.get('citation_id')
  const [selectedModel, setSelectedModel] = useState('gpt-5-mini')

  // Data states
  const [citation, setCitation] = useState<Record<string, any> | null>(null)
  const [criteriaData, setCriteriaData] = useState<CriteriaData | null>(null)
  const [loadingCitation, setLoadingCitation] = useState(false)
  const [loadingCriteria, setLoadingCriteria] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  // Load citation row (and ensure fulltext is extracted if missing)
  async function fetchCitationById(id: string) {
    if (!srId || !id) return
    setLoadingCitation(true)
    try {
      const headers = getAuthHeaders()
      const res = await fetch(
        `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
        { method: 'GET', headers },
      )
      const data = await res.json().catch(() => ({}))
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
        if (ft) setFulltextStr(ft)
        const coordsAny = parseJson((data as any).fulltext_coords) ?? (data as any).fulltext_coords
        if (coordsAny && Array.isArray(coordsAny)) setFulltextCoords(coordsAny)
        const pagesAny = parseJson((data as any).fulltext_pages) ?? (data as any).fulltext_pages
        if (pagesAny && Array.isArray(pagesAny)) setFulltextPages(pagesAny)

        // If coords/pages missing, trigger backend extraction then refetch row
        const needExtract =
          !Array.isArray(coordsAny) || coordsAny.length === 0 || !Array.isArray(pagesAny) || pagesAny.length === 0
        if (needExtract) {
          try {
            const res2 = await fetch(
              `/api/can-sr/citations/full-text?action=extract&sr_id=${encodeURIComponent(
                srId || '',
              )}&citation_id=${encodeURIComponent(String(id || ''))}`,
              { method: 'POST', headers },
            )
            if (res2.ok) {
              const res3 = await fetch(
                `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                  String(id),
                )}`,
                { headers },
              )
              const row2 = await res3.json().catch(() => ({}))

              const ft2 = typeof (row2 as any).fulltext === 'string' ? (row2 as any).fulltext : null
              if (ft2) setFulltextStr(ft2)

              const coordsAny2 = parseJson((row2 as any).fulltext_coords) ?? (row2 as any).fulltext_coords
              if (coordsAny2 && Array.isArray(coordsAny2)) setFulltextCoords(coordsAny2)

              const pagesAny2 = parseJson((row2 as any).fulltext_pages) ?? (row2 as any).fulltext_pages
              if (pagesAny2 && Array.isArray(pagesAny2)) setFulltextPages(pagesAny2)
            }
          } catch (err) {
            console.warn('Failed to extract fulltext for overlay', err)
          }
        }
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

      // 1) Prefill from human_* (answers saved during L2 screening), for both L1 and L2 questions
      if (humanParsed && typeof humanParsed === 'object' && (humanParsed as any).selected !== undefined) {
        newSelections[idx] = (humanParsed as any).selected
      } else if (typeof humanParsed === 'string' && humanParsed) {
        newSelections[idx] = humanParsed
      }

      // 2) For L1 questions: show hint from prior L1 screening (llm_*), but do not prefill from it
      if (sourceFlags[idx] === 'l1') {
        if (llmParsed && typeof llmParsed === 'object' && (llmParsed as any).selected !== undefined) {
          newHints[idx] = String((llmParsed as any).selected ?? '')
        } else if (typeof llmParsed === 'string') {
          newHints[idx] = llmParsed
        }
      }

      // Always populate AI panel from prior LLM result for both L1 and L2 (similar to extract view)
      if (llmParsed && typeof llmParsed === 'object') {
        newAiPanels[idx] = llmParsed
        newPanelOpen[idx] = false
      } else if (typeof llmParsed === 'string' && llmParsed) {
        // Normalize simple string LLM values to object so UI can render suggestion
        newAiPanels[idx] = { selected: llmParsed }
        newPanelOpen[idx] = false
      }

      // For L2 questions: if no human selection present, allow llm_* to prefill the dropdown
      const hasSelection = newSelections[idx] !== undefined && newSelections[idx] !== ''
      if (sourceFlags[idx] === 'l2' && !hasSelection) {
        const aiSelected = (newAiPanels[idx] && typeof newAiPanels[idx].selected === 'string') ? newAiPanels[idx].selected : null
        if (aiSelected) {
          newSelections[idx] = aiSelected
        } else if (typeof llmParsed === 'string' && llmParsed) {
          newSelections[idx] = llmParsed
        }
      }
    })

    setSelections((prev) => ({ ...newSelections, ...prev }))
    setAiPanels((prev) => ({ ...newAiPanels, ...prev }))
    setPanelOpen((prev) => ({ ...newPanelOpen, ...prev }))
    setHintByIndex((prev) => ({ ...prev, ...newHints }))
  }, [citation, criteriaData, sourceFlags])

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
    } catch (err) {
      console.error('human_classify post error', err)
    }
  }

  async function onSelectOption(questionIndex: number, value: string) {
    // Update UI immediately
    setSelections((prev) => ({ ...prev, [questionIndex]: value }))

    // Persist human selection in background
    if (!criteriaData) return
    const question = criteriaData.questions[questionIndex]
    postHumanClassifyPayload(question, value)
  }

  // Call backend classify for a single question using fulltext template (screening_step='l2')
  async function classifyQuestion(questionIndex: number) {
    if (!srId || !citationId || !criteriaData) return
    const question = criteriaData.questions[questionIndex]
    const options = criteriaData.possible_answers[questionIndex] || []
    const xtra = criteriaData.additional_infos?.[questionIndex] || ''
    try {
      const headers = {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      }
      const bodyPayload: any = {
        question,
        options,
        screening_step: 'l2',
        xtra,
        model: selectedModel,
        temperature: 0.0,
        max_tokens: 1200,
      }
      // Provide full text directly to backend to prevent include_columns=None error.
      // If fulltext is not yet available, fall back to title/abstract to avoid backend crash.

      bodyPayload.citation_text = fulltextStr
      bodyPayload.include_columns = ['title', 'abstract']

      const res = await fetch(
        `/api/can-sr/screen?action=classify&sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
          String(citationId),
        )}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify(bodyPayload),
        },
      )
      const data = await res.json().catch(() => ({}))
      const classification =
        data?.classification_json ||
        data?.result ||
        data?.classification ||
        data?.llm_classification ||
        data
      if (classification && typeof classification === 'object') {
        // If classification.selected present, set as default selection
        if ((classification as any).selected !== undefined) {
          setSelections((prev) => ({
            ...prev,
            [questionIndex]: (classification as any).selected,
          }))
        }
        setAiPanels((prev) => ({ ...prev, [questionIndex]: classification }))
        setPanelOpen((prev) => ({ ...prev, [questionIndex]: false }))

        // Persist the model-chosen selection for auditability
        try {
          if ((classification as any).selected !== undefined && criteriaData) {
            const qText = criteriaData.questions[questionIndex]
            await postHumanClassifyPayload(
              qText,
              (classification as any).selected,
              (classification as any).explanation,
              (classification as any).confidence,
            )
          }
        } catch (err) {
          console.error('Failed to persist classification as human_classify', err)
        }
      } else {
        if (typeof data === 'string') {
          setSelections((prev) => ({ ...prev, [questionIndex]: data }))
        }
        setAiPanels((prev) => ({ ...prev, [questionIndex]: data || null }))
        setPanelOpen((prev) => ({ ...prev, [questionIndex]: false }))
      }
    } catch (err) {
      console.error('Classify API error', err)
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

  const workspace = useMemo(() => {
    if (loadingCitation)
      return <div className="text-sm text-gray-600">Loading citation...</div>
    if (!citation)
      return <div className="text-sm text-gray-600">Citation not found.</div>

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
  }, [citation, loadingCitation, srId, citationId, fulltextCoords, fulltextPages, fulltextStr, panelsKeyed])

  if (!srId || !citationId) {
    // guard - redirect already handled in effect but keep safe render
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title="Full Text Screening"
        backHref={`/can-sr/l2-screen?sr_id=${encodeURIComponent(srId || '')}`}
        right={
          <ModelSelector
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        }
      />

      <main className="mx-auto max-w-8xl px-3 py-3">
        <div className="grid grid-cols-12 gap-3">
          {/* Workspace (left) */}
          <div className="col-span-9">
              {workspace}
          </div>

          {/* Selection sidebar (right) */}
          <aside className="col-span-3">
            <div className="h-full space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm flex flex-col">
              <div>
                <h4 className="text-xl font-semibold text-gray-900 text-center">Screening Questions</h4>
              </div>

              {loadingCriteria ? (
                <div className="text-sm text-gray-600">Loading criteria...</div>
              ) : !criteriaData || criteriaData.questions.length === 0 ? (
                <div className="text-sm text-gray-600">
                  No L2 screening criteria found for this review.
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

                    return (
                      <div
                        key={idx}
                        className="rounded-md border border-gray-100 p-3"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-800">
                              {q}
                            </p>

                            {sourceFlags[idx] === 'l1' ? (
                              <p className="mt-1 text-xs text-gray-500">
                                Title/Abstract screening answer: {hintByIndex[idx] ?? '(none)'}
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
                                className="rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
                              >
                                <span className="inline-flex items-center gap-1">
                                  AI <Wand2 className="h-3 w-3" />
                                </span>
                              </button>
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
                                AI suggests{' '}
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
                                  {aiData.selected ?? '(no selection)'}
                                </span>
                              </div>
                              <div className="text-xs text-gray-500">
                                {panelOpen[idx] ? 'Minimize' : 'Maximize'}
                              </div>
                            </div>

                            {panelOpen[idx] ? (
                              <div className="mt-2 rounded-md border border-gray-100 bg-white p-3 text-sm whitespace-pre-wrap text-gray-800">
                                <div className="mt-2">
                                  <strong>Confidence:</strong>{' '}
                                  {String(aiData.confidence ?? '')}
                                </div>
                                <div className="mt-2">
                                  <strong>Explanation:</strong>
                                  <div className="mt-1 text-sm text-gray-700">
                                    {aiData.explanation ??
                                      aiData.llm_raw ??
                                      '(no explanation)'}
                                  </div>
                                </div>
                                {Array.isArray(aiData?.evidence_sentences) && aiData.evidence_sentences.length > 0 ? (
                                  <div className="mt-2">
                                    <strong>Evidence:</strong>
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {aiData.evidence_sentences.map((item: any, k: number) => {
                                        const isCoord = item && typeof item === 'object'
                                        const label = isCoord
                                          ? `Page ${String(item.page ?? item.page_number ?? item.pageNum ?? '?')}${item.text ? `: ${String(item.text).slice(0, 80)}` : ''}`
                                          : `Sentence ${String(item)}`
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
              <div className="flex items-center justify-between mt-4">
                <button
                  onClick={async () => {
                    if (!citationId || !srId) return
                    const cur = Number(citationId)
                    if (Number.isNaN(cur)) return
                    const target = String(cur - 1)
                    // proactively fetch and reset selection state so UI updates immediately
                    setSelections({})
                    setAiPanels({})
                    setPanelOpen({})
                    await fetchCitationById(target)
                    router.push(
                      `/can-sr/l2-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                        target,
                      )}`,
                    )
                  }}
                  className="rounded-md border bg-white px-4 py-2 text-sm shadow-sm hover:bg-gray-50"
                >
                  Previous Citation
                </button>
                <button
                  onClick={async () => {
                    if (!citationId || !srId) return
                    const cur = Number(citationId)
                    if (Number.isNaN(cur)) return
                    const target = String(cur + 1)
                    // proactively fetch and reset selection state so UI updates immediately
                    setSelections({})
                    setAiPanels({})
                    setPanelOpen({})
                    await fetchCitationById(target)
                    router.push(
                      `/can-sr/l2-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                        target,
                      )}`,
                    )
                  }}
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
                >
                  Next Citation
                </button>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  )
}
