'use client'

import React, { useEffect, useState, useRef } from 'react'

type Props = {
  open: boolean
  onClose: () => void
  srId: string | null
  initialEmails?: string[]
  authHeaders?: Record<string, string>
}

function isValidEmail(email: string) {
  // simple RFC-ish validation
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
}

export default function ManageUsersPopup({ open, onClose, srId, initialEmails = [], authHeaders }: Props) {
  const [emails, setEmails] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [loadingEmail, setLoadingEmail] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    setEmails(Array.isArray(initialEmails) ? initialEmails.slice() : [])
  }, [initialEmails])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  if (!open) return null

  const addEmailLocal = (emailRaw: string) => {
    const email = emailRaw.trim().toLowerCase()
    if (!email) return
    if (!isValidEmail(email)) {
      setError('Invalid email address')
      return
    }
    if (emails.includes(email)) {
      setError('Email already present')
      return
    }
    setError(null)
    setEmails((prev) => [...prev, email])
    setInput('')
    addEmailRemote(email)
  }

  const removeEmailLocal = (email: string) => {
    setEmails((prev) => prev.filter((e) => e !== email))
    removeEmailRemote(email)
  }

  async function addEmailRemote(email: string) {
    if (!srId) {
      setError('Missing review id')
      return
    }
    setLoadingEmail(email)
    try {
      const res = await fetch(`/api/can-sr/reviews/users?action=add&sr_id=${encodeURIComponent(srId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders || {}) },
        body: JSON.stringify({ user_email: email }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError((data && (data.error || data.detail)) || `Failed to add user (${res.status})`)
        // revert local add if server failed
        setEmails((prev) => prev.filter((e) => e !== email))
      } else {
        setError(null)
      }
    } catch (err: any) {
      console.error('Add user error', err)
      setError(err?.message || 'Network error while adding user')
      setEmails((prev) => prev.filter((e) => e !== email))
    } finally {
      setLoadingEmail(null)
    }
  }

  async function removeEmailRemote(email: string) {
    if (!srId) {
      setError('Missing review id')
      return
    }
    setLoadingEmail(email)
    try {
      const res = await fetch(`/api/can-sr/reviews/users?action=remove&sr_id=${encodeURIComponent(srId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders || {}) },
        body: JSON.stringify({ user_email: email }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError((data && (data.error || data.detail)) || `Failed to remove user (${res.status})`)
        // revert local remove if server failed
        setEmails((prev) => (prev.includes(email) ? prev : [...prev, email]))
      } else {
        setError(null)
      }
    } catch (err: any) {
      console.error('Remove user error', err)
      setError(err?.message || 'Network error while removing user')
      setEmails((prev) => (prev.includes(email) ? prev : [...prev, email]))
    } finally {
      setLoadingEmail(null)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',' || e.key === 'Tab') {
      e.preventDefault()
      if (input.trim()) addEmailLocal(input)
    } else if (e.key === 'Backspace' && !input && emails.length) {
      // remove last
      removeEmailLocal(emails[emails.length - 1])
    }
  }

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData('text') || ''
    const parts = pasted.split(/[\s,;]+/).map((p) => p.trim()).filter(Boolean)
    if (parts.length > 1) {
      e.preventDefault()
      parts.forEach((p) => addEmailLocal(p))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      <div className="relative z-10 w-full max-w-2xl rounded-lg bg-white p-6 shadow-lg">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Manage users</h3>
            <p className="mt-1 text-sm text-gray-600">Add or remove emails who can access this systematic review.</p>
          </div>
        </div>

        <div className="mt-4">
          <label className="mb-2 block text-sm font-medium text-gray-700">Users</label>

          <div className="flex flex-wrap gap-2">
            {emails.map((e) => (
              <div
                key={e}
                className="flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-sm text-gray-800"
              >
                <span>{e}</span>
                <button
                  onClick={() => removeEmailLocal(e)}
                  className="rounded-full p-1 hover:bg-gray-200"
                  aria-label={`Remove ${e}`}
                >
                  <svg className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fillRule="evenodd"
                      d="M6.28 5.22a.75.75 0 011.06 0L10 7.88l2.66-2.66a.75.75 0 111.06 1.06L11.06 8.94l2.66 2.66a.75.75 0 11-1.06 1.06L10 10l-2.66 2.66a.75.75 0 11-1.06-1.06L8.94 8.94 6.28 6.28a.75.75 0 010-1.06z"
                      clipRule="evenodd"
                    />
                  </svg>
                </button>
              </div>
            ))}
          </div>

          <div className="mt-3 flex items-center gap-3">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              onPaste={handlePaste}
              placeholder="Type an email and press Enter"
              className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-300"
            />
            <button
              onClick={() => {
                if (input.trim()) addEmailLocal(input)
              }}
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
            >
              Add
            </button>
          </div>

          {error ? <div className="mt-2 text-sm text-red-600">{error}</div> : null}
          {loadingEmail ? <div className="mt-2 text-sm text-gray-600">Processing {loadingEmail}...</div> : null}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-md border border-gray-200 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
