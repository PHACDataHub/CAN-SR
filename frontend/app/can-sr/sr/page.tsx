'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { ModelSelector } from '@/components/chat'
import { authenticatedFetch, getAuthToken, getTokenType } from '@/lib/auth'
import StackingCard from '@/components/can-sr/stacking-card'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import ManageUsersPopup from '@/components/can-sr/setup/manage-users-popup'
import { Settings } from 'lucide-react'

export default function CanSrLandingPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')

  const [selectedModel, setSelectedModel] = useState('gpt-4o')
  const [manageOpen, setManageOpen] = useState(false)
  const token = getAuthToken()
  const tokenType = getTokenType()
  const authHeaders: Record<string, string> | undefined = token
    ? { Authorization: `${tokenType} ${token}` }
    : undefined
  const [sr, setSr] = useState<any>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!srId) {
      // require sr_id — redirect back to SR list if missing
      router.replace('/can-sr')
      return
    }

    const fetchSr = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await authenticatedFetch(
          `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}`,
        )
        if (!res.ok) {
          const errBody = await res.json().catch(() => ({}))
          throw new Error(
            errBody?.detail ||
              errBody?.error ||
              `Failed to fetch SR (${res.status})`,
          )
        }
        const data = await res.json().catch(() => ({}))
        setSr(data)
      } catch (err: any) {
        console.error('Error fetching SR:', err)
        setError(err?.message || 'Unable to load review')
      } finally {
        setLoading(false)
      }
    }

    fetchSr()
  }, [srId, router])

  console.log(sr)

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />

      <SRHeader
        title="CAN-SR"
        srName={loading ? "" : sr.name}
        showSettings={false}
        showExport={true}
        showBack={true}
        backHref="/can-sr"
        backLabel="Back to SRs"
        right={
          <div className="flex items-center">
            <button
              type="button"
              onClick={() => setManageOpen(true)}
              className="hidden items-center space-x-2 rounded-md border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 md:flex"
            >
              <Settings className="h-4 w-4 text-gray-600" />
              <span>Manage Users</span>
            </button>
          </div>
        }
      />

      {/* Main content */}
      <main className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-6">
          {loading ? (
            <div className="rounded-md border border-gray-200 bg-white p-6 text-sm text-gray-700">
              Loading review...
            </div>
          ) : error ? (
            <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {error}
            </div>
          ) : (
            <>
              <h3 className="text-2xl font-bold text-gray-900">{sr.name}</h3>
              <p className="mt-1 text-sm text-gray-600">{sr.description}</p>
            </>
          )}
        </div>

        <div className="space-y-3">
          <StackingCard
            title="Database Search"
            description="Select database and define search criteria"
            href={
              srId
                ? `/can-sr/search?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/search'
            }
          />
          <StackingCard
            title="Import references and criteria"
            description="Upload citation files, define eligibility criteria and review settings."
            href={
              srId
                ? `/can-sr/setup?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/setup'
            }
          />

          <StackingCard
            title="Title and abstract screening"
            description="Screen titles and abstracts to identify potentially relevant citations."
            href={
              srId
                ? `/can-sr/l1-screen?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/l1-screen'
            }
          />

          <StackingCard
            title="Full text review"
            description="Review full text articles and make inclusion/exclusion decisions."
            href={
              srId
                ? `/can-sr/l2-screen?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/l2-screen'
            }
          />

          <StackingCard
            title="Extraction"
            description="Extract outcome and study parameters for included studies."
            href={
              srId
                ? `/can-sr/extract?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/extract'
            }
          />
        </div>
      </main>

      <ManageUsersPopup
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        srId={srId}
        initialEmails={
          (sr && (sr.users || sr.user_emails || sr.allowed_users)) || []
        }
        authHeaders={authHeaders}
      />
    </div>
  )
}
