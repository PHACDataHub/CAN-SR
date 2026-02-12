import { GET } from '@/app/api/search/route'
import { Citation } from '@/components/chat/types'
import { getAuthToken, getTokenType } from '@/lib/auth'
import { useParams, useRouter } from 'next/navigation'
import React, { ChangeEvent, useEffect, useRef, useState } from 'react'
import { Bot, Check } from 'lucide-react'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

type CitationInfo = {
  citationIds: number[]
  srId: string
  questions: string[]
  possible_answers: string[][]
  include: string[]
  screeningStep: string
  pageview: string
}

type decisionPayload = {
  decision_maker: string
  screening_step: string
  decision: string
}

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const tokenType = getTokenType()
  return token
    ? { Authorization: `${tokenType} ${token}` }
    : ({} as Record<string, string>)
}

function snakeCaseColumn(name: string, llm: boolean) {
  if (!name) return 'llm_col'
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
  const [citationData, setCitationData] = useState<any[]>([])
  const [page, setpage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [lastPage, setLastpage] = useState(
    Math.ceil(citationIds.length / pageSize),
  )
  const [llmClassified, setLlmClassified] = useState<Record<number, boolean>>(
    {},
  )
  const [humanVerified, setHumanVerified] = useState<Record<number, boolean>>(
    {},
  )
  const fileInputRefs = useRef<Record<number, HTMLInputElement | null>>({})
  const [showClassify, setShowClassify] = useState<Record<number, boolean>>({})
  const router = useRouter()
  const dict = useDictionary()

  useEffect(() => {
    const fetchCitations = async () => {
      if (!citationIds) return
      const startIndex = (page - 1) * pageSize
      const endIndex = page * pageSize
      const results = await Promise.all(
        citationIds
          .slice(startIndex, endIndex)
          .map((id) => getCitationById(id)),
      )
      setCitationData(results)
      setLastpage(Math.ceil(citationIds.length / pageSize))
    }

    fetchCitations()
  }, [citationIds, page, pageSize])

  const getCitationById = async (id: number) => {
    if (!srId) return
    try {
      const headers = getAuthHeaders()
      const res = await fetch(
        `/api/can-sr/citations/get?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
        {
          method: 'GET',
          headers,
        },
      )
      const data = await res.json().catch(() => ({}))
      checkCitationStatus(data)
      return { id: data.id, title: data.title, abstract: data.abstract }
    } finally {
    }
  }
  const checkCitationStatus = async (data: any) => {
    let classified = true
    let verified = true
    questions.forEach((question) => {
      const llmQuestion = snakeCaseColumn(question, true)
      const humanQuestion = snakeCaseColumn(question, false)

      if (!data[llmQuestion]) {
        classified = false
      }
      if (!data[humanQuestion]) {
        verified = false
      }
    })
    if (classified) {
      setLlmClassified((prev) => ({
        ...prev,
        [data.id]: true,
      }))
    }
    if (verified) {
      setHumanVerified((prev) => ({
        ...prev,
        [data.id]: true,
      }))
    }
    if (data['fulltext_url']) {
      setShowClassify((prev) => ({
        ...prev,
        [data.id]: true,
      }))
    }
  }

  const changePageSize = (e: ChangeEvent<HTMLInputElement>) => {
    const target = e.target as HTMLInputElement
    let newPageSize = Number(target.value)
    if (newPageSize < 1) {
      newPageSize = 1
    } else if (newPageSize > citationIds.length) {
      newPageSize = citationIds.length
    }
    setPageSize(newPageSize)
  }

  const classifyCitationById = async (id: number) => {
    try {
      const headers = getAuthHeaders()
      if (!srId) return
      for (let i = 0; i < questions.length; i++) {
        const bodyPayload = {
          question: questions[i],
          options: possible_answers[i],
          include_columns: ['title', 'abstract'],
          screening_step: screeningStep,
        }
        const classifyRes = await fetch(
          `/api/can-sr/screen?action=classify&sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify(bodyPayload),
          },
        )
        const classifyData = await classifyRes.json().catch(() => ({}))
      }
      setLlmClassified((prev) => ({
        ...prev,
        [id]: true,
      }))
    } finally {
    }
  }

  const onChooseFile = (id: number) => {
    fileInputRefs.current[id]?.click()
  }

  const handleFileChange = async (
    event: React.ChangeEvent<HTMLInputElement>,
    id: number,
  ) => {
    const headers = getAuthHeaders()
    if (!event.target.files) return
    const file = event.target.files[0]
    const fd = new FormData()
    fd.append('file', file)
    if (file && file.type === 'application/pdf') {
      const res = await fetch(
        `/api/can-sr/citations/full-text?sr_id=${encodeURIComponent(srId)}&citation_id=${encodeURIComponent(id)}`,
        {
          method: 'POST',
          headers,
          body: fd as any,
        },
      )
      setShowClassify((prev) => ({
        ...prev,
        [id]: true,
      }))
    } else {
      alert(dict.common.invalidPDF)
    }
  }

  // Get current language to prepend to href links
  const { lang } = useParams<{ lang: string }>();

  return (
    <div className="flex flex-col items-center space-y-4">
      <ul className="space-y-2">
        {citationData.map((data) => (
          <li
            key={data.id}
            className="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 px-4 py-2"
          >
            <div className="flex flex-col space-y-2">
              <p className="text-xs text-gray-600"> Citation #{data.id} </p>
              <p className="text-semibold text">{data.title}</p>
              <p className="line-clamp-5 overflow-hidden text-sm text-ellipsis text-gray-800">
                {dict.common.abstract}: {data.abstract}
              </p>
            </div>
            <div className="flex flex-col items-center justify-center space-y-3">
              <button
                onClick={() =>
                  router.push(
                    `/${lang}/can-sr/${encodeURIComponent(pageview)}/view?sr_id=${encodeURIComponent(
                      srId || '',
                    )}&citation_id=${data.id}&screening=${screeningStep}`,
                  )
                }
                className="w-[80px] rounded-md bg-emerald-600 px-3 py-1 text-sm font-medium text-white hover:bg-emerald-700"
              >
                {dict.common.view}
              </button>
              {screeningStep != 'l1' ? (
                <button
                  className="w-[80px] rounded-md bg-emerald-600 px-3 py-1 text-sm font-medium text-white hover:bg-emerald-700"
                  onClick={() => onChooseFile(data.id)}
                >
                  {dict.common.upload}
                </button>
              ) : (
                <></>
              )}
              {screeningStep != 'l1' ? (
                <input
                  type="file"
                  accept="application/pdf"
                  ref={(el: HTMLInputElement | null): void => {
                    fileInputRefs.current[data.id] = el
                  }}
                  onChange={(event) => handleFileChange(event, data.id)}
                  style={{ display: 'none' }}
                />
              ) : (
                <></>
              )}
              {screeningStep != 'l2' || showClassify[data.id] ? (
                <button
                  onClick={() => {
                    classifyCitationById(data.id)
                  }}
                  className="w-[80px] rounded-md bg-emerald-600 px-3 py-1 text-sm font-medium text-white hover:bg-emerald-700"
                >
                  {dict.common.classify}
                </button>
              ) : (
                <></>
              )}

              <div className="align-center flex flex-row items-center space-x-4">
                {llmClassified[data.id] && (
                  <Bot className="h-6 w-6 text-green-600" />
                )}
                {humanVerified[data.id] && (
                  <Check className="h-6 w-6 text-green-600" />
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-col items-center space-y-3">
        <div className="flex flex-row items-center space-x-2">
          <label htmlFor="pageInput" className="text-gray-700">
            {dict.common.citationsPerPage}
          </label>
          <input
            name="pageInput"
            type="number"
            min="1"
            max={citationIds.length}
            onChange={changePageSize}
            value={pageSize}
            className="p-y-2 w-11 border p-1 text-gray-700"
          />
        </div>
        <div className="flex flex-row items-center space-x-8">
          <button
            className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:bg-gray-300 disabled:opacity-50"
            disabled={page === 1}
            onClick={() => setpage(page - 1)}
          >
            {dict.common.prev}
          </button>
          <p className="text-gray-700">
            {dict.common.pageOf.replace('{page}', String(page)).replace('{total}', String(lastPage))}
          </p>
          <button
            className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:bg-gray-300 disabled:opacity-50"
            disabled={page === lastPage}
            onClick={() => setpage(page + 1)}
          >
            {dict.common.next}
          </button>
        </div>
      </div>
    </div>
  )
}
