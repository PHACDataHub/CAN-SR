'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import ReferencesWorkspace from '@/components/can-sr/references/references-workspace'
import { authenticatedFetch } from '@/lib/auth'
import { useDictionary } from '../../DictionaryProvider'

export default function ReferencesPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const dict = useDictionary()
  const [hasDataset, setHasDataset] = useState<boolean | null>(null)
  const load = useCallback(async () => {
    if (!srId) return
    const response = await authenticatedFetch(
      `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}`,
    )
    if (response.ok) {
      const review = await response.json().catch(() => ({}))
      setHasDataset(Boolean(review?.screening_db?.table_name))
    }
  }, [srId])
  useEffect(() => {
    if (!srId) router.replace('/can-sr')
    else void load()
  }, [load, router, srId])
  if (!srId) return null
  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title={dict.references.title}
        backHref={`/can-sr/sr?sr_id=${encodeURIComponent(srId)}`}
      />
      <main className="mx-auto max-w-4xl px-6 py-10">
        <h3 className="text-xl font-semibold text-gray-900">
          {dict.references.heading}
        </h3>
        <p className="mt-2 text-sm text-gray-600">
          {dict.references.description}
        </p>
        <ReferencesWorkspace
          srId={srId}
          hasDataset={hasDataset}
          copy={dict.references as unknown as Record<string, string>}
        />
      </main>
    </div>
  )
}
