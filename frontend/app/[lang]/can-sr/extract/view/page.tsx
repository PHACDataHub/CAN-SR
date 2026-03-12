'use client'

import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useState, useEffect, useRef } from 'react'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { getAuthToken, getTokenType } from '@/lib/auth'
import { ModelSelector } from '@/components/chat'
import PDFBoundingBoxViewer, { PDFBoundingBoxViewerHandle } from '@/components/can-sr/PDFBoundingBoxViewer'
import { ChevronDown, ChevronRight, Wand2 } from 'lucide-react'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

export default function CanSrL2ScreenPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const citationId = searchParams?.get('citation_id')
  // Get current language to keep language when navigating (must be unconditional hook call)
  const { lang } = useParams<{ lang: string }>()
  const [selectedModel, setSelectedModel] = useState('gpt-5-mini')
  const dict = useDictionary()

  // Navigation list (Extract is filtered by L2 pass)
  const [citationIdList, setCitationIdList] = useState<number[]>([])

  type ParametersParsed = {
    categories: string[]
    possible_parameters: string[][]
    descriptions: string[][]
  }

  const getAuthHeaders = (): Record<string, string> => {
    const token = getAuthToken()
    const tokenType = getTokenType()
    return token ? { Authorization: `${tokenType} ${token}` } : {}
  }

  // Load filtered citation ids for navigation (Extract is filtered by L2 pass)
  useEffect(() => {
    if (!srId) return
    const loadIds = async () => {
      try {
        const headers = getAuthHeaders()
        const res = await fetch(
          `/api/can-sr/citations/list?sr_id=${encodeURIComponent(srId)}&filter=${encodeURIComponent('l2')}`,
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

  // Column name helpers to mirror backend snake_case and column derivation
  const snakeCase = (name: string, maxLen = 63): string => {
    if (!name) return ''
    let s = name.trim().toLowerCase()
    s = s.replace(/[^\w]+/g, '_')
    s = s.replace(/_+/g, '_').replace(/^_+|_+$/g, '')
    if (/^\d/.test(s)) s = `c_${s}`
    return s.slice(0, maxLen)
  }

  const snakeCaseParamLLM = (name: string): string => {
    const core = snakeCase(name, 52)
    const col = core ? `llm_param_${core}` : 'llm_param_param'
    return col.slice(0, 60)
  }

  const humanParamColumn = (name: string): string => {
    const llmCol = snakeCaseParamLLM(name)
    return llmCol.replace('llm_param_', 'human_param_')
  }

  const [parametersParsed, setParametersParsed] = useState<ParametersParsed | null>(null)
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [savingParam, setSavingParam] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<Record<string, string>>({})
  const [descOpen, setDescOpen] = useState<Record<string, boolean>>({})
  const toggleDesc = (name: string) =>
    setDescOpen((prev) => ({ ...prev, [name]: !prev[name] }))

  const [paramFound, setParamFound] = useState<Record<string, boolean>>({})
  const [aiStatus, setAiStatus] = useState<Record<string, string>>({})
  const [aiPanels, setAiPanels] = useState<Record<string, any>>({})
  const [panelOpen, setPanelOpen] = useState<Record<string, boolean>>({})
  const [fulltextCoords, setFulltextCoords] = useState<any[] | null>(null)
  const [fulltextPages, setFulltextPages] = useState<{ width: number; height: number }[] | null>(null)
  const [fulltextStr, setFulltextStr] = useState<string | null>(null)
  const viewerRef = useRef<PDFBoundingBoxViewerHandle | null>(null)

  // Table/Figure artifacts (for evidence chips -> click to highlight)
  const [fulltextTables, setFulltextTables] = useState<any[] | null>(null)
  const [fulltextFigures, setFulltextFigures] = useState<any[] | null>(null)

  const scrollToArtifact = (kind: 'table' | 'figure', idx: number) => {
    const list = kind === 'table' ? (fulltextTables || []) : (fulltextFigures || [])
    const item = list.find((x: any) => Number(x?.index) === Number(idx))
    console.log('[artifact-click]', { kind, idx, hasViewer: !!viewerRef.current, item })
    if (!item || !viewerRef.current) return
    const bbox = item?.bounding_box
    const first = Array.isArray(bbox) ? bbox[0] : null
    console.log('[artifact-bbox]', { kind, idx, bbox, first })
    if (!first) return
    viewerRef.current.scrollToCoord(first)
  }

  const [runningAllAI, setRunningAllAI] = useState(false)
  const [runAllProgress, setRunAllProgress] = useState<{ done: number; total: number } | null>(null)

  // Cache full text so single-param and run-all don’t repeatedly trigger extraction/DB reads
  const fullTextCacheRef = useRef<string | null>(null)
  const fullTextInFlightRef = useRef<Promise<string | null> | null>(null)

  const ensureFullText = async (): Promise<string | null> => {
    if (!citationId || !srId) return null
    if (fullTextCacheRef.current) return fullTextCacheRef.current
    if (fullTextInFlightRef.current) return fullTextInFlightRef.current

    const p = (async () => {
      const headers = getAuthHeaders()

      // Step 1: trigger full-text extraction (idempotent; backend short-circuits via MD5)
      const res1 = await fetch(
        `/api/can-sr/citations/full-text?action=extract&sr_id=${encodeURIComponent(
          srId || '',
        )}&citation_id=${encodeURIComponent(String(citationId || ''))}`,
        {
          method: 'POST',
          headers,
        },
      )

      let fullText: string | null = null
      if (res1.ok) {
        const d1 = await res1.json().catch(() => null)
        if (d1 && typeof d1 === 'object') {
          fullText = (d1 as any).fulltext ?? null
        }
      }

      // Step 2: fallback to DB row
      if (!fullText) {
        const citRes = await fetch(
          `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId || '')}&citation_id=${encodeURIComponent(
            String(citationId || ''),
          )}`,
          { headers },
        )
        const row = await citRes.json().catch(() => null)
        if (row && typeof row === 'object') {
          fullText = (row as any).fulltext ?? null
        }
      }

      if (typeof fullText === 'string' && fullText.length > 0) {
        fullTextCacheRef.current = fullText
        setFulltextStr(fullText)
      }
      return fullText
    })()

    fullTextInFlightRef.current = p
    try {
      return await p
    } finally {
      fullTextInFlightRef.current = null
    }
  }

  const suggestParam = async (name: string, description: string) => {
    if (!citationId || !srId) return
    setAiStatus(prev => ({ ...prev, [name]: 'extracting' }))
    try {
      const headers = getAuthHeaders()
      const fullText = await ensureFullText()
      setAiStatus(prev => ({ ...prev, [name]: 'suggesting' }))
      const res = await fetch(
        `/api/can-sr/extract?action=extract-parameter&sr_id=${encodeURIComponent(
          srId || '',
        )}&citation_id=${encodeURIComponent(String(citationId || ''))}`,
        {
          method: 'POST',
          headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fulltext: fullText ?? undefined,
            parameter_name: name,
            parameter_description: description || name,
            model: selectedModel,
            temperature: 0.0,
            max_tokens: 512,
          }),
        },
      )
      const data = await res.json().catch(() => ({}))
      const ext = data?.extraction || data
      if (res.ok && ext) {
        setParamValues(prev => ({ ...prev, [name]: ext?.value ?? '' }))
        setParamFound(prev => ({ ...prev, [name]: !!ext?.found }))
        setAiPanels(prev => ({ ...prev, [name]: ext }))
        setPanelOpen(prev => ({ ...prev, [name]: false }))
        setAiStatus(prev => ({ ...prev, [name]: 'suggested' }))
      } else {
        setAiStatus(prev => ({ ...prev, [name]: 'error' }))
      }
    } catch {
      setAiStatus(prev => ({ ...prev, [name]: 'error' }))
    }
  }

  const runAllAI = async () => {
    if (!parametersParsed || runningAllAI) return

    // Flatten rendered parameters with their descriptions
    const params: Array<{ name: string; description: string }> = []
    parametersParsed.categories.forEach((_, i) => {
      ;(parametersParsed.possible_parameters[i] || []).forEach((param, j) => {
        const desc = parametersParsed.descriptions?.[i]?.[j] || ''
        const cleanDesc = desc.replace(/<\/?desc>/g, '')
        const paramName =
          typeof param === 'string' ? param : Array.isArray(param) ? param[0] : String(param)
        params.push({ name: paramName, description: cleanDesc })
      })
    })

    setRunningAllAI(true)
    setRunAllProgress({ done: 0, total: params.length })
    try {
      // Warm fulltext cache once
      await ensureFullText()

      for (let idx = 0; idx < params.length; idx++) {
        const p = params[idx]
        await suggestParam(p.name, p.description)
        setRunAllProgress({ done: idx + 1, total: params.length })
      }
    } finally {
      setRunningAllAI(false)
      // keep progress around as “done”; user can see it completed
    }
  }

  useEffect(() => {
    if (!srId) return
    const headers = getAuthHeaders()
    ;(async () => {
      try {
        const res = await fetch(
          `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}&criteria_parsed=1`,
          { headers },
        )
        const data = await res.json().catch(() => ({}))
        const parsed = data?.criteria_parsed || data?.criteria || {}
        const paramsInfo = parsed?.parameters
        if (paramsInfo && paramsInfo.categories && paramsInfo.possible_parameters) {
          setParametersParsed(paramsInfo)
          const defaults: Record<string, string> = {}
          paramsInfo.possible_parameters.forEach((arr: string[]) => {
            arr.forEach((name: string) => {
              defaults[name] = defaults[name] || ''
            })
          })
          setParamValues(prev => ({ ...defaults, ...prev }))
          const defaultFound: Record<string, boolean> = {}
          paramsInfo.possible_parameters.forEach((arr: string[]) => {
            arr.forEach((name: string) => {
              defaultFound[name] = defaultFound[name] ?? false
            })
          })
          setParamFound(prev => ({ ...defaultFound, ...prev }))
        }
      } catch (err) {
        console.warn('Failed to load parameters', err)
      }
    })()
  }, [srId])

  // Prefill parameter values from citation row (human_param_* preferred, llm_param_* as fallback suggestion)
  useEffect(() => {
    if (!srId || !citationId || !parametersParsed) return
    const headers = getAuthHeaders()
    ;(async () => {
      try {
        const res = await fetch(
          `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
            String(citationId),
          )}`,
          { headers },
        )
        const row = await res.json().catch(() => ({}))
        if (!res.ok || !row || typeof row !== 'object') return

        const nextFound: Record<string, boolean> = {}
        const nextValues: Record<string, string> = {}
        const nextAIPanels: Record<string, any> = {}

        const parseJson = (v: any) => {
          if (!v) return null
          try {
            return typeof v === 'string' ? JSON.parse(v) : v
          } catch {
            return null
          }
        }

        parametersParsed.possible_parameters.forEach((arr: string[]) => {
          arr.forEach((name: string) => {
            const humanCol = humanParamColumn(name)
            const llmCol = snakeCaseParamLLM(name)
            const humanVal = parseJson((row as any)[humanCol])
            const llmVal = parseJson((row as any)[llmCol])

            // Prefer human value over LLM for the textbox/found flag
            if (humanVal && typeof humanVal === 'object') {
              nextFound[name] = !!(humanVal.found ?? humanVal.value)
              nextValues[name] = humanVal.value ?? ''
            } else if (llmVal && typeof llmVal === 'object') {
              nextFound[name] = !!llmVal.found
              nextValues[name] = llmVal.value ?? ''
            }

            // Always populate AI panel with LLM extraction (explanation/evidence) when available
            if (llmVal && typeof llmVal === 'object') {
              nextAIPanels[name] = llmVal
            }
          })
        })

        if (Object.keys(nextFound).length) {
          setParamFound(prev => ({ ...prev, ...nextFound }))
        }
        if (Object.keys(nextValues).length) {
          setParamValues(prev => ({ ...prev, ...nextValues }))
        }
        if (Object.keys(nextAIPanels).length) {
          setAiPanels(prev => ({ ...prev, ...nextAIPanels }))
        }

        // extract coords/pages/fulltext and artifacts for PDF overlay
        const ft = typeof (row as any).fulltext === 'string' ? (row as any).fulltext : null
        if (ft) setFulltextStr(ft)

        const tablesAny = parseJson((row as any).fulltext_tables) ?? (row as any).fulltext_tables
        if (tablesAny && Array.isArray(tablesAny)) setFulltextTables(tablesAny)

        const figsAny = parseJson((row as any).fulltext_figures) ?? (row as any).fulltext_figures
        if (figsAny && Array.isArray(figsAny)) setFulltextFigures(figsAny)

        const coordsAny = parseJson((row as any).fulltext_coords) ?? (row as any).fulltext_coords
        if (coordsAny && Array.isArray(coordsAny)) setFulltextCoords(coordsAny)

        const pagesAny = parseJson((row as any).fulltext_pages) ?? (row as any).fulltext_pages
        if (pagesAny && Array.isArray(pagesAny)) setFulltextPages(pagesAny)
      } catch (err) {
        console.warn('Failed to prefill citation params', err)
      }
    })()
  }, [srId, citationId, parametersParsed])

  // Always fetch citation row to populate PDF overlay data (independent of parameters)
  useEffect(() => {
    if (!srId || !citationId) return
    const headers = getAuthHeaders()
    ;(async () => {
      try {
        const res = await fetch(
          `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
            String(citationId),
          )}`,
          { headers },
        )
        const row = await res.json().catch(() => ({}))
        if (!res.ok || !row || typeof row !== 'object') return

        const parseJson = (v: any) => {
          if (!v) return null
          try {
            return typeof v === 'string' ? JSON.parse(v) : v
          } catch {
            return null
          }
        }

        const ft = typeof (row as any).fulltext === 'string' ? (row as any).fulltext : null
        if (ft) setFulltextStr(ft)

        const tablesAny = parseJson((row as any).fulltext_tables) ?? (row as any).fulltext_tables
        if (tablesAny && Array.isArray(tablesAny)) setFulltextTables(tablesAny)

        const figsAny = parseJson((row as any).fulltext_figures) ?? (row as any).fulltext_figures
        if (figsAny && Array.isArray(figsAny)) setFulltextFigures(figsAny)

        const coordsAny = parseJson((row as any).fulltext_coords) ?? (row as any).fulltext_coords
        if (coordsAny && Array.isArray(coordsAny)) setFulltextCoords(coordsAny)

        const pagesAny = parseJson((row as any).fulltext_pages) ?? (row as any).fulltext_pages
        if (pagesAny && Array.isArray(pagesAny)) setFulltextPages(pagesAny)

        // If coords/pages are missing, trigger backend extraction to populate them, then refetch
        const needExtract =
          !Array.isArray(coordsAny) || coordsAny.length === 0 || !Array.isArray(pagesAny) || pagesAny.length === 0

        if (needExtract) {
          try {
            const res2 = await fetch(
              `/api/can-sr/citations/full-text?action=extract&sr_id=${encodeURIComponent(
                srId || '',
              )}&citation_id=${encodeURIComponent(String(citationId || ''))}`,
              { method: 'POST', headers },
            )
            if (res2.ok) {
              const res3 = await fetch(
                `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(
                  String(citationId),
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
      } catch (err) {
        console.warn('Failed to load citation overlay data', err)
      }
    })()
  }, [srId, citationId])

  const updateValue = (name: string, val: string) => {
    setParamValues(prev => ({ ...prev, [name]: val }))
  }

  const saveParam = async (name: string) => {
    if (!citationId || !srId) return
    setSavingParam(name)
    setSaveStatus(prev => ({ ...prev, [name]: 'saving' }))
    try {
      const headers = getAuthHeaders()
      const res = await fetch(
        `/api/can-sr/extract?action=human-extract-parameter&sr_id=${encodeURIComponent(
          srId || '',
        )}&citation_id=${encodeURIComponent(citationId || '')}`,
        {
          method: 'POST',
          headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            parameter_name: name,
            found: paramFound[name] ?? !!paramValues[name],
            value: paramValues[name] || null,
            explanation: '',
            evidence_sentences: [],
            reviewer: null,
          }),
        },
      )
      await res.json().catch(() => ({}))
      setSaveStatus(prev => ({ ...prev, [name]: res.ok ? 'saved' : 'error' }))
    } catch {
      setSaveStatus(prev => ({ ...prev, [name]: 'error' }))
    } finally {
      setSavingParam(null)
    }
  }

  if (!srId) {
    // require sr_id — redirect back to SR list if missing
    router.replace('/can-sr')
    return
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />

      <SRHeader 
        title={dict.screening.parameterExtraction}
        srName=""
        backHref={`/can-sr/extract?sr_id=${encodeURIComponent(srId || '')}`}
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
            {/* <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm"> */}
              {/* <div className="border-b pb-4 mb-4 text-center">
                <h3 className="text-lg font-semibold text-gray-900">Workspace</h3>
                <p className="mt-2 text-sm text-gray-600">
                  This area displays the full text (PDF) and is a flexible workspace for viewing and selecting parameter regions.
                </p>
              </div> */}

              <PDFBoundingBoxViewer
                srId={srId || ''}
                citationId={citationId ?? ''}
                conversionId={null}
                fileName={"Fulltext"}
                coords={fulltextCoords || []}
                pages={fulltextPages || []}
                aiPanels={aiPanels}
                panelOpen={panelOpen}
                fulltext={fulltextStr || ''}
                defaultFitToWidth={true}
                ref={viewerRef}
              />

            {/* </div> */}
          </div>

          {/* Selection sidebar (right) */}
          <aside className="col-span-3">
            <div className="h-full space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm flex flex-col">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <h4 className="text-xl font-semibold text-gray-900">{dict.extract.parameters}</h4>
                  <button
                    type="button"
                    onClick={runAllAI}
                    disabled={!parametersParsed || runningAllAI}
                    className="rounded-md border px-2 py-1 text-xs hover:bg-gray-50 disabled:opacity-50"
                    title={dict.extract.runAllAI}
                  >
                    <span className="inline-flex items-center gap-1">
                      {dict.extract.runAllAI} <Wand2 className="h-3 w-3" />
                    </span>
                  </button>
                </div>
                {runAllProgress && runAllProgress.total > 0 ? (
                  <div className="mt-1 text-xs text-gray-500">
                    {runningAllAI
                      ? `${dict.extract.running} ${runAllProgress.done}/${runAllProgress.total}`
                      : `${dict.extract.ran} ${runAllProgress.done}/${runAllProgress.total}`}
                  </div>
                ) : null}
                {/* <p className="mt-2 text-sm text-gray-600 text-center">
                  This is the area of the UI where you can select the human answer — the AI-selected answer is used as guidance.
                </p> */}
              </div>

              <div className="rounded-md border border-gray-100 p-3 h-[680px] overflow-y-auto">
                {parametersParsed ? (
                  <div className="space-y-4">
                    {parametersParsed.categories.map((cat, i) => (
                      <div key={cat} className="space-y-2">
                        <h5 className="text-sm font-semibold text-gray-900">{cat}</h5>
                        <div className="space-y-3">
                          {(parametersParsed.possible_parameters[i] || []).map((param, j) => {
                            const desc = parametersParsed.descriptions?.[i]?.[j] || ''
                            const cleanDesc = desc.replace(/<\/?desc>/g, '')
                            const paramName = typeof param === 'string' ? param : Array.isArray(param) ? param[0] : String(param)
                            return (
                              <div key={paramName} className="rounded-md border border-gray-200 p-2">
                                <div className="flex items-start justify-between">
                                  <div className="text-xs font-medium text-gray-700 flex items-center gap-1">
                                    {paramName}
                                    {cleanDesc ? (
                                      <button
                                        type="button"
                                        onClick={() => toggleDesc(paramName)}
                                        className="ml-1 inline-flex items-center text-gray-400 hover:text-gray-600"
                                        aria-label={descOpen[paramName] ? dict.extract.hideDescription : dict.extract.showDescription}
                                        title={descOpen[paramName] ? dict.extract.hideDescription : dict.extract.showDescription}
                                      >
                                        {descOpen[paramName] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                      </button>
                                    ) : null}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs text-gray-500">
                                      {saveStatus[paramName] === 'saved'
                                        ? dict.extract.saved
                                        : saveStatus[paramName] === 'error'
                                        ? dict.extract.error
                                        : saveStatus[paramName] === 'saving'
                                        ? dict.extract.saving
                                        : ''}
                                    </span>
                                    <span className="text-xs text-gray-500">
                                      {aiStatus[paramName] === 'extracting'
                                        ? dict.extract.extractingFullText
                                        : aiStatus[paramName] === 'suggesting' || aiStatus[paramName] === 'loading'
                                        ? dict.extract.suggesting
                                        : aiStatus[paramName] === 'suggested'
                                        ? dict.extract.finished
                                        : aiStatus[paramName] === 'error'
                                        ? dict.extract.aiError
                                        : ''}
                                    </span>
                                    <button
                                      onClick={() => suggestParam(paramName, cleanDesc)}
                                      disabled={
                                        runningAllAI ||
                                        aiStatus[paramName] === 'loading' ||
                                        aiStatus[paramName] === 'extracting' ||
                                        aiStatus[paramName] === 'suggesting'
                                      }
                                      className="rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
                                    >
                                      <span className="inline-flex items-center gap-1">
                                        AI <Wand2 className="h-3 w-3" />
                                      </span>
                                    </button>
                                    <button
                                      onClick={() => saveParam(paramName)}
                                      disabled={savingParam === paramName}
                                      className="rounded-md bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                                    >
                                      {dict.common.save}
                                    </button>
                                  </div>
                                </div>
                                {cleanDesc && descOpen[paramName] ? (
                                  <p className="mt-1 text-xs text-gray-500">{cleanDesc}</p>
                                ) : null}
                                <input
                                  type="text"
                                  value={paramValues[paramName] || ''}
                                  onChange={(e) => updateValue(paramName, e.target.value)}
                                  placeholder={dict.extract.enterValue}
                                  className="mt-2 w-full rounded-md border px-2 py-1 text-sm"
                                />

                                {aiPanels[paramName] ? (
                                  <div className="mt-2">
                                    <div
                                      onClick={() =>
                                        setPanelOpen((prev) => ({
                                          ...prev,
                                          [paramName]: !Boolean(prev[paramName]),
                                        }))
                                      }
                                      style={{ cursor: 'pointer' }}
                                      className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-2"
                                    >
                                      <div className="text-xs">
                                        {typeof aiPanels[paramName]?.value === 'string' && aiPanels[paramName]?.value.trim().length > 0 ? (
                                          <>
                                            {dict.extract.aiSuggested}{' '}
                                            <span className="ml-1 text-xs font-medium text-emerald-600">
                                              {aiPanels[paramName]?.value}
                                            </span>
                                          </>
                                        ) : (
                                          <span className="text-xs text-gray-600">{dict.extract.noAISuggestion}</span>
                                        )}
                                      </div>
                                      <div className="text-xs text-gray-500">
                                        {panelOpen[paramName] ? dict.screening.minimize : dict.screening.maximize}
                                      </div>
                                    </div>
                                    {panelOpen[paramName] ? (
                                      <div className="mt-2 rounded-md border border-gray-100 bg-white p-3 text-xs whitespace-pre-wrap text-gray-800">
                                        <div className="mt-2">
                                          <strong>{dict.screening.explanation}</strong>
                                          <div className="mt-1 text-xs text-gray-700">
                                            {aiPanels[paramName]?.explanation ??
                                              aiPanels[paramName]?.llm_raw ??
                                              dict.screening.noExplanation}
                                          </div>
                                        </div>
{Array.isArray(aiPanels[paramName]?.evidence_sentences) ? (
  <div className="mt-2">
    <strong>{dict.screening.evidence}</strong>
    <div className="mt-1 flex flex-wrap gap-1">
      {aiPanels[paramName].evidence_sentences.map((item: any, k: number) => {
        const isCoord = item && typeof item === 'object'
        const label = isCoord
          ? `${dict.screening.page} ${String(item.page ?? item.page_number ?? item.pageNum ?? '?')}${item.text ? `: ${String(item.text).slice(0, 80)}` : ''}`
          : `${dict.screening.sentence} ${String(item)}`
        const onClick = () => {
          if (!viewerRef.current) return
          if (isCoord) {
            viewerRef.current.scrollToCoord(item)
          } else {
            const idx = Number(item)
            if (!Number.isNaN(idx)) {
              viewerRef.current.scrollToSentenceIndex(idx)
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

{Array.isArray(aiPanels[paramName]?.evidence_tables) && aiPanels[paramName].evidence_tables.length > 0 ? (
  <div className="mt-2">
    <strong>Evidence tables:</strong>
    <div className="mt-1 flex flex-wrap gap-1">
      {aiPanels[paramName].evidence_tables.map((t: any, k: number) => {
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

{Array.isArray(aiPanels[paramName]?.evidence_figures) && aiPanels[paramName].evidence_figures.length > 0 ? (
  <div className="mt-2">
    <strong>Evidence figures:</strong>
    <div className="mt-1 flex flex-wrap gap-1">
      {aiPanels[paramName].evidence_figures.map((f: any, k: number) => {
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
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-gray-600 text-center py-6">
                    {dict.extract.noParameters}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between">
                <button
                  onClick={async () => {
                    if (!citationId || !srId) return
                    const cur = Number(citationId)
                    if (Number.isNaN(cur)) return
                    const idx = citationIdList.indexOf(cur)
                    if (idx <= 0) return
                    const target = String(citationIdList[idx - 1])
                    router.push(
                      `/${lang}/can-sr/extract/view?sr_id=${encodeURIComponent(
                        srId,
                      )}&citation_id=${encodeURIComponent(target)}`,
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
                    router.push(
                      `/${lang}/can-sr/extract/view?sr_id=${encodeURIComponent(
                        srId,
                      )}&citation_id=${encodeURIComponent(target)}`,
                    )
                  }}
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
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
