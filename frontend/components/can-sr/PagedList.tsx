import { getAuthToken, getTokenType } from '@/lib/auth'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'
import { Bot, Check } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import React, { ChangeEvent, useEffect, useRef, useState } from 'react'

type CitationInfo = {
  citationIds: number[]
  srId: string
  questions: string[]
  possible_answers: string[][]
  include: string[]
  screeningStep: string
  pageview: string
}

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const tokenType = getTokenType()
  return token ? { Authorization: `${tokenType} ${token}` } : {}
}

function snakeCaseColumn(name: string, llm: boolean) {
  if (!name) return llm ? 'llm_col' : 'human_col'
  let s = name.trim().toLowerCase()
  s = s.replace(/[^\w]+/g, '_')
  s = s.replace(/_+/g, '_').replace(/^_+|_+$/g, '')
  return llm ? `llm_${s}`.slice(0, 60) : `human_${s}`.slice(0, 60)
}

export default function PagedList({
  citationIds,
  srId,
  questions,
  possible_answers,
  screeningStep,
  pageview,
}: CitationInfo) {
  const router = useRouter()
  const { lang } = useParams<{ lang: string }>()
  const dict = useDictionary()

  const [citationData, setCitationData] = useState<any[]>([])
  const [page, setpage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [lastPage, setLastpage] = useState(1)

  const [llmClassified, setLlmClassified] = useState<Record<number, boolean>>(
    {},
  )
  const [humanVerified, setHumanVerified] = useState<Record<number, boolean>>(
    {},
  )
  const [showClassify, setShowClassify] = useState<Record<number, boolean>>({})

  const fileInputRefs = useRef<Record<number, HTMLInputElement | null>>({})

  // --- paging ---
  useEffect(() => {
    const lp = Math.max(1, Math.ceil((citationIds?.length || 0) / pageSize))
    setLastpage(lp)
    if (page > lp) setpage(lp)
    if (page < 1) setpage(1)
  }, [citationIds, pageSize])

  // keep lastPage updated when page/pageSize changes too (defensive)
  useEffect(() => {
    setLastpage(Math.max(1, Math.ceil((citationIds?.length || 0) / pageSize)))
  }, [citationIds, pageSize, page])

  useEffect(() => {
    const fetchCitations = async () => {
      if (!citationIds?.length) {
        setCitationData([])
        return
      }
      const startIndex = (page - 1) * pageSize
      const endIndex = page * pageSize
      const results = await Promise.all(
        citationIds.slice(startIndex, endIndex).map((id) => getCitationById(id)),
      )
      setCitationData(results.filter(Boolean))
    }
    fetchCitations()
  }, [citationIds, page, pageSize])

  const getCitationById = async (id: number) => {
    if (!srId) return
    const headers = getAuthHeaders()
    const res = await fetch(
      `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
      { method: 'GET', headers },
    )
    const data = await res.json().catch(() => ({}))
    checkCitationStatus(data)
    return { id: data.id, title: data.title, abstract: data.abstract }
  }

  const checkCitationStatus = (data: any) => {
    let classified = true
    let verified = true
    questions.forEach((question) => {
      const llmQuestion = snakeCaseColumn(question, true)
      const humanQuestion = snakeCaseColumn(question, false)
      if (!data?.[llmQuestion]) classified = false
      if (!data?.[humanQuestion]) verified = false
    })

    if (classified) {
      setLlmClassified((prev) => ({ ...prev, [data.id]: true }))
    }
    if (verified) {
      setHumanVerified((prev) => ({ ...prev, [data.id]: true }))
    }
    if (data?.fulltext_url) {
      setShowClassify((prev) => ({ ...prev, [data.id]: true }))
    }
  }

  const changePageSize = (e: ChangeEvent<HTMLSelectElement>) => {
    const v = Number(e.target.value)
    const newPageSize = [10, 25, 50, 100].includes(v) ? v : 25
    setPageSize(newPageSize)
    setpage(1)
  }

  const [jumpPageInput, setJumpPageInput] = useState<string>('')
  const jumpToPage = () => {
    const n = Number(jumpPageInput)
    if (Number.isNaN(n)) return
    const clamped = Math.min(Math.max(1, n), lastPage)
    setpage(clamped)
  }

  const classifyCitationById = async (id: number) => {
    const headers = {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    }
    if (!srId) return

    for (let i = 0; i < questions.length; i++) {
      const bodyPayload = {
        question: questions[i],
        options: possible_answers[i],
        include_columns: ['title', 'abstract'],
        screening_step: screeningStep,
      }
      await fetch(
        `/api/can-sr/screen?action=classify&sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
        { method: 'POST', headers, body: JSON.stringify(bodyPayload) },
      )
    }
    setLlmClassified((prev) => ({ ...prev, [id]: true }))
  }

  const onChooseFile = (id: number) => {
    fileInputRefs.current[id]?.click()
  }

  const handleFileChange = async (
    event: React.ChangeEvent<HTMLInputElement>,
    id: number,
  ) => {
    if (!event.target.files) return
    const file = event.target.files[0]
    if (!file) return

    if (file.type !== 'application/pdf') {
      alert(dict.common.invalidPDF)
      return
    }

    // Only warn about re-upload/reset if a PDF already exists for this citation.
    // (We treat `showClassify[id]` as the “has existing fulltext” flag, since it
    // is set when `fulltext_url` is present.)
    if (showClassify[id]) {
      const ok = window.confirm(dict.common.uploadWillReset)
      if (!ok) {
        event.target.value = ''
        return
      }
    }

    const headers = getAuthHeaders()
    const fd = new FormData()
    fd.append('file', file)

    await fetch(
      `/api/can-sr/citations/full-text?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
      { method: 'POST', headers, body: fd as any },
    )

    setShowClassify((prev) => ({ ...prev, [id]: true }))
  }

  return (
    <div className="flex flex-col items-center space-y-4">
      <ul className="w-full space-y-2">
        {citationData.map((data) => (
          <li
            key={data.id}
            className="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 px-4 py-2"
          >
            <div className="flex flex-col space-y-2 pr-4">
              <p className="text-xs text-gray-600">Citation #{data.id}</p>
              <p className="text-semibold text">{data.title}</p>
              <p className="line-clamp-5 overflow-hidden text-ellipsis text-sm text-gray-800">
                {dict.common.abstract}: {data.abstract}
              </p>
            </div>

            <div className="flex flex-col items-center justify-center space-y-3">
              <button
                onClick={() =>
                  router.push(
                    `/${lang}/can-sr/${encodeURIComponent(pageview)}/view?sr_id=${encodeURIComponent(srId || '')}&citation_id=${data.id}&screening=${screeningStep}`,
                  )
                }
                className="w-[90px] rounded-md bg-emerald-600 px-3 py-1 text-sm font-medium text-white hover:bg-emerald-700"
              >
                {dict.common.view}
              </button>

              {screeningStep !== 'l1' ? (
                <>
                  <button
                    className="w-[90px] rounded-md bg-emerald-600 px-3 py-1 text-sm font-medium text-white hover:bg-emerald-700"
                    onClick={() => onChooseFile(data.id)}
                  >
                    {dict.common.upload}
                  </button>
                  <input
                    type="file"
                    accept="application/pdf"
                    ref={(el: HTMLInputElement | null): void => {
                      fileInputRefs.current[data.id] = el
                    }}
                    onChange={(event) => handleFileChange(event, data.id)}
                    style={{ display: 'none' }}
                  />
                </>
              ) : null}

              {screeningStep !== 'l2' || showClassify[data.id] ? (
                <button
                  onClick={() => classifyCitationById(data.id)}
                  className="w-[90px] rounded-md bg-emerald-600 px-3 py-1 text-sm font-medium text-white hover:bg-emerald-700"
                >
                  {dict.common.classify}
                </button>
              ) : null}

              <div className="align-center flex flex-row items-center space-x-4">
                {llmClassified[data.id] ? (
                  <Bot className="h-6 w-6 text-green-600" />
                ) : null}
                {humanVerified[data.id] ? (
                  <Check className="h-6 w-6 text-green-600" />
                ) : null}
              </div>
            </div>
          </li>
        ))}
      </ul>

      {/* Modern pagination footer */}
      <div className="sticky bottom-0 flex w-full flex-wrap items-center justify-between gap-3 rounded-md border border-gray-100 bg-white p-3">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-700">
            {dict.common.citationsPerPage}
          </label>
          <select
            value={pageSize}
            onChange={changePageSize}
            className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm"
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <button
            className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
            disabled={page <= 1}
            onClick={() => setpage(1)}
            title={dict.common.first}
            type="button"
          >
            {dict.common.first}
          </button>
          <button
            className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
            disabled={page <= 1}
            onClick={() => setpage(page - 1)}
            type="button"
          >
            {dict.common.prev}
          </button>
          <p className="min-w-[140px] text-center text-sm text-gray-700">
            {dict.common.pageOf
              .replace('{page}', String(page))
              .replace('{total}', String(lastPage))}
          </p>
          <button
            className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
            disabled={page >= lastPage}
            onClick={() => setpage(page + 1)}
            type="button"
          >
            {dict.common.next}
          </button>
          <button
            className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
            disabled={page >= lastPage}
            onClick={() => setpage(lastPage)}
            title={dict.common.last}
            type="button"
          >
            {dict.common.last}
          </button>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-700">{dict.common.jumpToPage}</label>
          <input
            value={jumpPageInput}
            onChange={(e) => setJumpPageInput(e.target.value)}
            className="w-20 rounded-md border border-gray-200 px-2 py-1 text-sm"
            placeholder={String(page)}
            inputMode="numeric"
          />
          <button
            type="button"
            onClick={jumpToPage}
            className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700"
          >
            {dict.common.go}
          </button>
        </div>
      </div>
    </div>
  )
}
