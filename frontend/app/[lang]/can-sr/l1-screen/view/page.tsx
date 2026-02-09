'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
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
    (expected fields: selected, explanation, confidence, llm_raw)
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

/* Types for local clarity */
type CriteriaData = {
  questions: string[]
  possible_answers: string[][]
}

/* Main page component */
export default function CanSrL1ScreenPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const citationId = searchParams?.get('citation_id')
  const [selectedModel, setSelectedModel] = useState('gpt-5-mini')
  const dict = useDictionary()

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

  useEffect(() => {
    if (!srId || !citationId) {
      router.replace('/can-sr')
      return
    }
  }, [srId, citationId, router])

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

  // When citation + criteria are loaded, initialize selection defaults from AI columns
  useEffect(() => {
    if (!citation || !criteriaData) return

    const newSelections: Record<number, string> = {}
    const newAiPanels: Record<number, any> = {}
    const newPanelOpen: Record<number, boolean> = {}

    criteriaData.questions.forEach((q: string, idx: number) => {
      const col = snakeCaseColumn(q)
      const aiVal = citation[col]
      // citation stored value may be JSON string or object depending on backend
      if (aiVal !== undefined && aiVal !== null) {
        // Try parse if string
        let parsed = aiVal
        if (typeof aiVal === 'string') {
          try {
            parsed = JSON.parse(aiVal)
          } catch {
            // not JSON — store raw string as selected if it matches an option
            parsed = aiVal
          }
        }
        // If parsed is object and contains 'selected', default to that
        if (
          parsed &&
          typeof parsed === 'object' &&
          parsed.selected !== undefined
        ) {
          newSelections[idx] = parsed.selected
          newAiPanels[idx] = parsed
          newPanelOpen[idx] = false
        } else if (typeof parsed === 'string') {
          newSelections[idx] = parsed
        }
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
    } catch (err) {
      console.error('human_classify post error', err)
    }
  }

  async function onSelectOption(questionIndex: number, value: string) {
    // Update UI immediately
    setSelections((prev) => ({ ...prev, [questionIndex]: value }))

    // Persist human selection in background (fire-and-forget)
    if (!criteriaData) return
    const question = criteriaData.questions[questionIndex]
    postHumanClassifyPayload(question, value)
  }

  // Handler: call backend classify endpoint for a single question
  async function classifyQuestion(questionIndex: number) {
    if (!srId || !citationId || !criteriaData) return
    const question = criteriaData.questions[questionIndex]
    const options = criteriaData.possible_answers[questionIndex] || []
    try {
      const headers = {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      }
      const bodyPayload = {
        question,
        options,
        include_columns: ['title', 'abstract'],
        screening_step: 'l1',
      }
      const res = await fetch(
        `/api/can-sr/screen?action=classify&sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
          citationId,
        )}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify(bodyPayload),
        },
      )
      const data = await res.json().catch(() => ({}))
      // Expect the backend to return the classification_json or similar structure
      // Try flexible extraction:
      const classification =
        data?.classification_json ||
        data?.result ||
        data?.classification ||
        data?.llm_classification ||
        data
      if (classification && typeof classification === 'object') {
        // If classification.selected present, set as default selection
        if (classification.selected !== undefined) {
          setSelections((prev) => ({
            ...prev,
            [questionIndex]: classification.selected,
          }))
        }
        setAiPanels((prev) => ({ ...prev, [questionIndex]: classification }))
        setPanelOpen((prev) => ({ ...prev, [questionIndex]: false }))

        // Persist the (model-chosen) selection as a human_classify entry so the selected answer is saved.
        // We include explanation/confidence when available to aid auditability.
        try {
          if (classification.selected !== undefined && criteriaData) {
            const qText = criteriaData.questions[questionIndex]
            // await so we ensure persistence attempt before returning control (but failures are non-fatal)
            await postHumanClassifyPayload(
              qText,
              classification.selected,
              classification.explanation,
              classification.confidence,
            )
          }
        } catch (err) {
          console.error(
            'Failed to persist classification as human_classify',
            err,
          )
        }
      } else {
        // If server returned a simple string, set it as selection
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

  // Render helpers
  const workspace = useMemo(() => {
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
  }, [citation, loadingCitation, dict])

  if (!srId || !citationId) {
    // guard - redirect already handled in effect but keep safe render
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title={dict.screening.titleAbstract}
        backHref={`/can-sr/l1-screen?sr_id=${encodeURIComponent(srId || '')}`}
        backLabel={dict.cansr.backToCitations}
        right={
          <ModelSelector
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        }
      />

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="grid grid-cols-12 gap-6">
          {/* Workspace (left) */}
          <div className="col-span-7">
            <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
              {workspace}
            </div>
          </div>

          {/* Selection sidebar (right) */}
          <aside className="col-span-5">
            <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h4 className="text-md font-semibold text-gray-900">{dict.screening.selection}</h4>
              <p className="text-sm text-gray-600">
                {dict.screening.selectionDesc}
              </p>

              {loadingCriteria ? (
                <div className="text-sm text-gray-600">{dict.screening.loadingCriteria}</div>
              ) : !criteriaData || criteriaData.questions.length === 0 ? (
                <div className="text-sm text-gray-600">
                  {dict.screening.noCriteria}
                </div>
              ) : (
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
            </div>
          </aside>
        </div>
        <div className="mt-6 flex justify-between">
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
                `/can-sr/l1-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                  target,
                )}`,
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
              const target = String(cur + 1)
              // proactively fetch and reset selection state so UI updates immediately
              setSelections({})
              setAiPanels({})
              setPanelOpen({})
              await fetchCitationById(target)
              router.push(
                `/can-sr/l1-screen/view?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                  target,
                )}`,
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
