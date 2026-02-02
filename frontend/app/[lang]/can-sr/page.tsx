'use client'

import React, { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import StackingCard from '@/components/can-sr/stacking-card'
import { getAuthToken, getTokenType, type User } from '@/lib/auth'

type SRItem = {
  id?: string
  sr_id?: string
  name?: string
  title?: string
  description?: string
}

/**
 * Page: Manage all systematic reviews the current user is a part of.
 *
 * - Uses GCHeader and SRHeader from components/can-sr/headers.tsx
 * - Displays reviews using StackingCard
 * - Adds a "Create review" button in the SRHeader right area that opens a modal.
 * - Modal POSTs to /api/can-sr/reviews/create (frontend proxy) with JSON { name, description }
 */

export default function CanSrIndexPage() {
  const [reviews, setReviews] = useState<SRItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [user, setUser] = useState<User | null>(null)
  const [isUserLoading, setIsUserLoading] = useState(true)

  const router = useRouter()

  // Modal state
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  async function fetchReviews() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/can-sr/reviews/list', { method: 'GET', headers: getAuthHeaders() })
      if (!res.ok) {
        throw new Error(`Failed to fetch (${res.status})`)
      }
      const data = await res.json()
      // backend may return list in different shapes; normalize to array
      const list = Array.isArray(data) ? data : data?.items || []
      setReviews(list)
    } catch (err: any) {
      console.error('Error fetching SRs', err)
      setError('Unable to load reviews')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchReviews()
  }, [])

  async function handleCreate(e?: React.FormEvent) {
    if (e) e.preventDefault()
    if (!name.trim()) {
      setError('Please provide a name for the review.')
      return
    }
    setCreating(true)
    setError(null)
    try {
      // Use FormData (multipart) so backend FastAPI Form() parameters are satisfied
      const fd = new FormData()
      fd.append('name', name.trim())
      if (description.trim()) {
        fd.append('description', description.trim())
      }

      const res = await fetch('/api/can-sr/reviews/create', {
        method: 'POST',
        body: fd,
        headers: getAuthHeaders(),
      })

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        // backend FastAPI may return detail or error fields
        throw new Error(errBody?.detail || errBody?.error || `Create failed: ${res.status}`)
      }

      const created = await res.json().catch(() => ({}))
      // refresh the list and close modal
      await fetchReviews()
      setShowCreate(false)
      setName('')
      setDescription('')
    } catch (err: any) {
      console.error('Create SR error', err)
      setError(err?.message || 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  // Get auth headers
  const getAuthHeaders = (): Record<string, string> => {
    const token = getAuthToken()
    const tokenType = getTokenType()

    if (!token) {
      return {}
    }

    return { Authorization: `${tokenType} ${token}` }
  }

  // Fetch current user and ensure logged in
  useEffect(() => {
    const fetchUser = async () => {
      try {
        const token = getAuthToken()
        if (!token) {
          router.push('/login')
          return
        }

        const response = await fetch('/api/auth/me', {
          headers: getAuthHeaders(),
        })

        if (!response.ok) {
          throw new Error('Failed to fetch user data')
        }

        const data = await response.json()
        setUser(data.user)
      } catch (error) {
        console.error('Error fetching user data:', error)
        router.push('/login')
      } finally {
        setIsUserLoading(false)
      }
    }

    fetchUser()
  }, [router])

  const rightNode = (
    <div className="flex items-center space-x-2">
      <button
        type="button"
        onClick={() => setShowCreate(true)}
        className="rounded-md border border-gray-200 bg-white px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        Create review
      </button>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />
      <SRHeader
        title="CAN‑SR"
        showSettings={false}
        showExport={false}
        showBack={true}
        backHref='/'
        backLabel='Back to Home'
        right={rightNode}
      />

      <main className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-6">
          <h3 className="text-2xl font-bold text-gray-900">Your Systematic Reviews</h3>
          <p className="mt-1 text-sm text-gray-600">
            View and manage the systematic reviews you are a member of. Create a new review using the
            "Create review" button.
          </p>
        </div>

        {loading ? (
          <div className="rounded-md border border-gray-200 bg-white p-6 text-center text-sm text-gray-700">Loading reviews...</div>
        ) : error ? (
          <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        ) : reviews.length === 0 ? (
          <div className="space-y-4">
            
            <div className="rounded-md border border-gray-200 bg-white p-6 text-sm text-gray-700">
              You are not part of any reviews yet.
            </div>
            <div>
              <button
                onClick={() => setShowCreate(true)}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
              >
                Create your first review
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {reviews.map((r, idx) => {
              const title = r.name || r.title || `Review ${r.sr_id || r.id || idx + 1}`
              const desc = r.description || r.title || undefined
              // Link to SR page: use sr_id or id if present, else fallback to '#'
              const id = r.sr_id || r.id
              const href = id ? `/can-sr/sr?sr_id=${encodeURIComponent(id)}` : '/can-sr/sr'
              return (
                <StackingCard key={id || idx} title={title} description={desc} href={href} />
              )
            })}
          </div>
        )}
      </main>

      {/* Create modal */}
      {showCreate ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => {
              if (!creating) {
                setShowCreate(false)
                setError(null)
              }
            }}
          />
          <div className="relative z-10 w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
            <h4 className="text-lg font-semibold text-gray-900">Create new review</h4>
            <form className="mt-4 space-y-4" onSubmit={(e) => handleCreate(e)}>
              <div>
                <label className="block text-sm font-medium text-gray-700">Name</label>
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  placeholder="e.g., Effects of X on Y"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700">Description (optional)</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </div>

              {error ? <div className="text-sm text-red-600">{error}</div> : null}

              <div className="flex justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => {
                    if (!creating) {
                      setShowCreate(false)
                      setError(null)
                    }
                  }}
                  className="rounded-md border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={creating}
                  className={`rounded-md px-4 py-1 text-sm font-medium text-white ${creating ? 'bg-emerald-300' : 'bg-emerald-600 hover:bg-emerald-700'}`}
                >
                  {creating ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  )
}
