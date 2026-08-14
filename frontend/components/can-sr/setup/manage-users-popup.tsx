'use client'

import React, { useEffect, useState, useRef } from 'react'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'
import { getCurrentUser } from '@/lib/auth'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

type Props = {
  open: boolean
  onClose: () => void
  srId: string | null
  initialEmails?: string[]
  authHeaders?: Record<string, string>
}

type Member = { member_id: string; role: 'owner' | 'member' }

function isValidEmail(email: string) {
  // simple RFC-ish validation
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
}

export default function ManageUsersPopup({
  open,
  onClose,
  srId,
  initialEmails = [],
  authHeaders,
}: Props) {
  const [members, setMembers] = useState<Member[]>([])
  const [input, setInput] = useState('')
  const [loadingEmail, setLoadingEmail] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [currentUserEmail, setCurrentUserEmail] = useState<string | null>(null)
  const [membersLoaded, setMembersLoaded] = useState(false)
  const [roleChangeMember, setRoleChangeMember] = useState<Member | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dict = useDictionary()

  useEffect(() => {
    setMembers(
      Array.isArray(initialEmails)
        ? initialEmails.map((member_id) => ({ member_id, role: 'member' }))
        : [],
    )
  }, [initialEmails])

  useEffect(() => {
    if (!open || !srId) return
    setMembersLoaded(false)
    fetch(`/api/can-sr/reviews/users?sr_id=${encodeURIComponent(srId)}`, {
      headers: authHeaders,
    })
      .then(async (res) => ({ res, data: await res.json().catch(() => ({})) }))
      .then(({ res, data }) => {
        if (res.ok) setMembers(data.members || [])
        else setError(data.error || data.detail || 'Failed to load members')
      })
      .catch(() => setError('Failed to load members'))
      .finally(() => setMembersLoaded(true))
  }, [open, srId, authHeaders])

  useEffect(() => {
    if (!open) return
    let active = true
    getCurrentUser().then((user) => {
      if (active) setCurrentUserEmail(user?.email?.trim().toLowerCase() || null)
    })
    return () => {
      active = false
    }
  }, [open])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  if (!open) return null

  const ownerCount = members.filter((member) => member.role === 'owner').length
  const currentUserRole = members.find(
    (member) => member.member_id.trim().toLowerCase() === currentUserEmail,
  )?.role
  const canManage = membersLoaded && currentUserRole === 'owner'

  const addEmailLocal = (emailRaw: string) => {
    if (!canManage) return
    const email = emailRaw.trim().toLowerCase()
    if (!email) return
    if (!isValidEmail(email)) {
      setError(dict.users.invalidEmail)
      return
    }
    if (members.some((member) => member.member_id === email)) {
      setError(dict.users.emailExists)
      return
    }
    setError(null)
    setMembers((prev) => [...prev, { member_id: email, role: 'member' }])
    setInput('')
    addEmailRemote(email)
  }

  const removeEmailLocal = (member: Member) => {
    if (!canManage || (member.role === 'owner' && ownerCount <= 1)) return
    setMembers((prev) =>
      prev.filter((item) => item.member_id !== member.member_id),
    )
    removeEmailRemote(member)
  }

  async function addEmailRemote(email: string) {
    if (!srId) {
      setError(dict.users.missingReviewId)
      return
    }
    setLoadingEmail(email)
    try {
      const res = await fetch(
        `/api/can-sr/reviews/users?action=add&sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authHeaders || {}),
          },
          body: JSON.stringify({ user_email: email }),
        },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(
          (data && (data.error || data.detail)) ||
            `Failed to add user (${res.status})`,
        )
        // revert local add if server failed
        setMembers((prev) =>
          prev.filter((member) => member.member_id !== email),
        )
      } else {
        setError(null)
      }
    } catch (err: any) {
      console.error('Add user error', err)
      setError(err?.message || 'Network error while adding user')
      setMembers((prev) => prev.filter((member) => member.member_id !== email))
    } finally {
      setLoadingEmail(null)
    }
  }

  async function removeEmailRemote(member: Member) {
    const email = member.member_id
    if (!srId) {
      setError(dict.users.missingReviewId)
      return
    }
    setLoadingEmail(email)
    try {
      const res = await fetch(
        `/api/can-sr/reviews/users?action=remove&sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authHeaders || {}),
          },
          body: JSON.stringify({ user_email: email }),
        },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(
          (data && (data.error || data.detail)) ||
            `Failed to remove user (${res.status})`,
        )
        // revert local remove if server failed
        setMembers((prev) =>
          prev.some((item) => item.member_id === email)
            ? prev
            : [...prev, member],
        )
      } else {
        setError(null)
      }
    } catch (err: any) {
      console.error('Remove user error', err)
      setError(err?.message || 'Network error while removing user')
      setMembers((prev) =>
        prev.some((item) => item.member_id === email)
          ? prev
          : [...prev, member],
      )
    } finally {
      setLoadingEmail(null)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',' || e.key === 'Tab') {
      e.preventDefault()
      if (input.trim()) addEmailLocal(input)
    } else if (canManage && e.key === 'Backspace' && !input && members.length) {
      // remove last
      removeEmailLocal(members[members.length - 1])
    }
  }

  async function confirmRoleChange() {
    const member = roleChangeMember
    if (
      !srId ||
      !member ||
      !canManage ||
      (member.role === 'owner' && ownerCount <= 1)
    )
      return
    const role = member.role === 'owner' ? 'member' : 'owner'
    setLoadingEmail(member.member_id)
    try {
      const res = await fetch(
        `/api/can-sr/reviews/users?sr_id=${encodeURIComponent(srId)}&member_id=${encodeURIComponent(member.member_id)}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            ...(authHeaders || {}),
          },
          body: JSON.stringify({ member_id: member.member_id, role }),
        },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok)
        throw new Error(data.error || data.detail || 'Failed to change role')
      setMembers((prev) =>
        prev.map((item) =>
          item.member_id === member.member_id ? { ...item, role } : item,
        ),
      )
      setRoleChangeMember(null)
    } catch (err: any) {
      setError(err.message || 'Failed to change role')
    } finally {
      setLoadingEmail(null)
    }
  }

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData('text') || ''
    const parts = pasted
      .split(/[\s,;]+/)
      .map((p) => p.trim())
      .filter(Boolean)
    if (parts.length > 1) {
      e.preventDefault()
      if (canManage) parts.forEach((p) => addEmailLocal(p))
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="manage-users-title"
    >
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      <div className="relative z-10 w-full max-w-2xl rounded-lg bg-white p-6 shadow-lg">
        <div className="flex items-start justify-between">
          <div>
            <h3
              id="manage-users-title"
              className="text-lg font-semibold text-gray-900"
            >
              {dict.users.manageTitle}
            </h3>
            <p className="mt-1 text-sm text-gray-600">
              {dict.users.manageDesc}
            </p>
          </div>
        </div>

        <div className="mt-4">
          <label className="mb-2 block text-sm font-medium text-gray-700">
            {dict.users.usersLabel}
          </label>

          <div className="flex flex-wrap gap-2">
            {members.map((member) => (
              <div
                key={member.member_id}
                className="flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-sm text-gray-800"
              >
                <span>{member.member_id}</span>
                <button
                  type="button"
                  onClick={() => setRoleChangeMember(member)}
                  disabled={
                    !canManage ||
                    loadingEmail !== null ||
                    (member.role === 'owner' && ownerCount <= 1)
                  }
                  title={
                    member.role === 'owner' && ownerCount <= 1
                      ? 'At least one owner must remain'
                      : undefined
                  }
                  className="rounded bg-white px-1 text-xs text-indigo-700 hover:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {member.role}
                </button>
                <button
                  type="button"
                  onClick={() => removeEmailLocal(member)}
                  disabled={
                    !canManage ||
                    loadingEmail !== null ||
                    (member.role === 'owner' && ownerCount <= 1)
                  }
                  title={
                    member.role === 'owner' && ownerCount <= 1
                      ? 'At least one owner must remain'
                      : undefined
                  }
                  className="rounded-full p-1 hover:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label={`Remove ${member.member_id}`}
                >
                  <svg
                    className="h-3 w-3"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
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
              disabled={!canManage || loadingEmail !== null}
              placeholder={dict.users.emailPlaceholder}
              className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:bg-gray-100"
            />
            <button
              type="button"
              disabled={!canManage || loadingEmail !== null}
              onClick={() => {
                if (input.trim()) addEmailLocal(input)
              }}
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {dict.common.add}
            </button>
          </div>

          {error ? (
            <div className="mt-2 text-sm text-red-600">{error}</div>
          ) : null}
          {membersLoaded && currentUserEmail && !canManage ? (
            <div className="mt-2 text-sm text-gray-600">
              Only review owners can manage members.
            </div>
          ) : null}
          {loadingEmail ? (
            <div className="mt-2 text-sm text-gray-600">
              {dict.users.processing} {loadingEmail}...
            </div>
          ) : null}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-md border border-gray-200 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            {dict.common.done}
          </button>
        </div>
      </div>
      <AlertDialog
        open={roleChangeMember !== null}
        onOpenChange={(open) => {
          if (!open && !loadingEmail) setRoleChangeMember(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {roleChangeMember?.role === 'owner'
                ? 'Demote review owner?'
                : 'Promote review member?'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {roleChangeMember?.role === 'owner'
                ? `${roleChangeMember.member_id} will remain a review member but will no longer be able to manage owners or owner-only actions.`
                : `${roleChangeMember?.member_id} will be able to manage owners and perform owner-only actions.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={loadingEmail !== null}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmRoleChange}
              disabled={loadingEmail !== null}
            >
              {loadingEmail
                ? 'Saving…'
                : roleChangeMember?.role === 'owner'
                  ? 'Demote'
                  : 'Promote'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
