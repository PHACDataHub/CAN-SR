'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import CriteriaEditor from '@/components/can-sr/setup/criteria-editor'
import { authenticatedFetch } from '@/lib/auth'
import { useDictionary } from '../../DictionaryProvider'

export default function ProtocolsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const dict = useDictionary()
  const [hasDataset, setHasDataset] = useState<boolean | null>(null)

  const loadReview = useCallback(async () => {
    if (!srId) return
    const response = await authenticatedFetch(
      `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}`,
    )
    if (!response.ok) return
    const review = await response.json().catch(() => ({}))
    setHasDataset(Boolean(review?.screening_db?.table_name))
  }, [srId])

  useEffect(() => {
    if (!srId) {
      router.replace('/can-sr')
      return
    }
    void loadReview()
  }, [loadReview, router, srId])

  if (!srId) return null

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title={dict.protocols.title}
        backHref={`/can-sr/sr?sr_id=${encodeURIComponent(srId)}`}
      />
      <main className="mx-auto max-w-4xl px-6 py-10">
        <h3 className="text-xl font-semibold text-gray-900">
          {dict.protocols.heading}
        </h3>
        <p className="mt-2 text-sm text-gray-600">
          {dict.protocols.description}
        </p>
        {hasDataset === false ? (
          <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p>{dict.protocols.noDataset}</p>
            <Link
              className="mt-2 inline-block font-medium underline"
              href={`/can-sr/references?sr_id=${encodeURIComponent(srId)}`}
            >
              {dict.protocols.addReferences}
            </Link>
          </div>
        ) : null}
        <section className="mt-6 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h4 className="mb-4 text-lg font-semibold text-gray-900">
            {dict.protocols.criteriaSection}
          </h4>
          <CriteriaEditor
            srId={srId}
            hasScreeningData={Boolean(hasDataset)}
            labels={
              dict.setup.criteriaBuilder as unknown as Record<string, string>
            }
          />
        </section>
      </main>
    </div>
  )
}
