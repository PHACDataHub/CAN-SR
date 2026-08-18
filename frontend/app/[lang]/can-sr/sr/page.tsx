'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { authenticatedFetch, getAuthToken, getTokenType } from '@/lib/auth'
import StackingCard from '@/components/can-sr/stacking-card'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import ManageUsersPopup from '@/components/can-sr/setup/manage-users-popup'
import { Settings } from 'lucide-react'
import { useDictionary } from '../../DictionaryProvider'

interface SRCostSummary {
  sr_id: string,
  currency: string,
  totals: {
    l1: number,
    l2: number,
    other: number,
    grand_total: number
  }
  breakdown: Record<string, number>
}

const COST_POLL_INTERVAL_MS = 15000

function formatCurrency(amount: number, currency?: string): string {
  const normalizedCurrency = String(currency || 'USD').trim().toUpperCase() || 'USD'
  return new Intl.NumberFormat('en-CA', {
    style: 'currency',
    currency: normalizedCurrency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount)
}

export default function CanSrLandingPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const dict = useDictionary()

  const [manageOpen, setManageOpen] = useState(false)
  const token = getAuthToken()
  const tokenType = getTokenType()
  const authHeaders: Record<string, string> | undefined = token
    ? { Authorization: `${tokenType} ${token}` }
    : undefined
  const [sr, setSr] = useState<any>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const [costs, setCosts] = useState<SRCostSummary | null>(null)
  const [costsLoading, setCostsLoading] = useState<boolean>(true)
  const [costsError, setCostsError] = useState<string | null>(null)

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

  useEffect(() => {
    if (!srId) return

    let cancelled = false

    const fetchCosts = async (isInitialLoad = false) => {
      if (isInitialLoad) {
        setCostsLoading(true)
      }

      try {
        const res = await authenticatedFetch(
          `/api/can-sr/reviews/costs?sr_id=${encodeURIComponent(srId)}`,
        )

        if (!res.ok) {
          const errBody = await res.json().catch(() => ({}))
          throw new Error(
            errBody?.detail ||
              errBody?.error ||
              `Failed to fetch costs (${res.status})`,
          )
        }

        const data: SRCostSummary = await res.json().catch(() => ({}))
        if (!cancelled) {
          setCosts(data)
          setCostsError(null)
        }
      } catch (err: any) {
        console.error('Error fetching costs:', err)
        if (!cancelled) {
          setCostsError(err?.message || 'Unable to load costs')
        }
      } finally {
        if (!cancelled) {
          setCostsLoading(false)
        }
      }
    }

    fetchCosts(true)

    const intervalId = setInterval(() => fetchCosts(false), COST_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      clearInterval(intervalId)
    }
  }, [srId])

  const renderCostMeta = (amount?: number) => {
    if (costsLoading) {
      return (
        <p className="text-sm text-emerald-800">
          Total Cost: <span className="font-medium">Loading...</span>
        </p>
      )
    }

    if (costsError) {
      return (
        <p className="text-sm text-amber-800">
          Total Cost is unavailable.
        </p>
      )
    }

    return (
      <p className="text-sm text-emerald-800">
        Total Cost: <span className="font-medium">{formatCurrency(amount || 0, costs?.currency)}</span>
      </p>
    )
  }

  // console.log(sr)

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />

      <SRHeader
        title={dict.cansr.title}
        srName={loading ? '' : sr?.name || ''}
        showSettings={false}
        showExport={true}
        showBack={true}
        backHref="/can-sr"
        backLabel={dict.cansr.backToSRs}
        right={
          <div className="flex items-center">
            <button
              type="button"
              onClick={() => setManageOpen(true)}
              className="hidden items-center space-x-2 rounded-md border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 md:flex"
            >
              <Settings className="h-4 w-4 text-gray-600" />
              <span>{dict.cansr.manageUsers}</span>
            </button>
          </div>
        }
      />

      {/* Main content */}
      <main className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-6">
          {loading ? (
            <div className="rounded-md border border-gray-200 bg-white p-6 text-sm text-gray-700">
              {dict.sr.loadingReview}
            </div>
          ) : error ? (
            <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {error}
            </div>
          ) : (
            <>
              <h3 className="text-2xl font-bold text-gray-900">{sr?.name || ''}</h3>
              <p className="mt-1 text-sm text-gray-600">{sr?.description || ''}</p>
            </>
          )}
        </div>

        <div className="space-y-3">
          <StackingCard
            title={dict.sr.referencesWorkspace}
            description={dict.sr.referencesWorkspaceDesc}
            href={
              srId
                ? `/can-sr/references?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/references'
            }
          />
          <StackingCard
            title={dict.sr.protocols}
            description={dict.sr.protocolsDesc}
            href={
              srId
                ? `/can-sr/protocols?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/protocols'
            }
          />

          <StackingCard
            title={dict.sr.titleAbstractScreening}
            description={dict.sr.titleAbstractScreeningDesc}
            href={
              srId
                ? `/can-sr/l1-screen?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/l1-screen'
            }
            expandedMeta={renderCostMeta(costs?.totals?.l1)}
          />

          <StackingCard
            title={dict.sr.fullTextReview}
            description={dict.sr.fullTextReviewDesc}
            href={
              srId
                ? `/can-sr/l2-screen?sr_id=${encodeURIComponent(srId)}`
                : '/can-sr/l2-screen'
            }
            expandedMeta={renderCostMeta(costs?.totals?.l2)}
          />

          <StackingCard
            title={dict.sr.extraction}
            description={dict.sr.extractionDesc}
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
