'use client'

import React, { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { getAuthToken, getTokenType } from '@/lib/auth'
import PagedList from '@/components/can-sr/PagedList'
import { Bot, Check } from 'lucide-react'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

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
}

export default function CitationsListPage({
  screeningStep,
  pageview,
}: CitationListData) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const srId = searchParams?.get('sr_id')
  const dict = useDictionary()

  const [citationIds, setCitationIds] = useState<number[] | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [exporting, setExporting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [criteriaData, setCriteriaData] = useState<CriteriaData | null>()

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

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title={displayMap[screeningStep]}
        backHref={`/can-sr/sr?sr_id=${encodeURIComponent(srId || '')}`}
        right={null}
      />

      <main className="mx-auto max-w-4xl px-6 py-10">
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

          <div className="mt-6">
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
                />
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
