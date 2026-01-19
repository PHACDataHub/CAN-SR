'use client'

import Image from 'next/image'
import { useRouter } from 'next/navigation'
import BackButton from '@/components/ui/backbutton'
import { InteractiveHoverButton } from '@/components/magicui/interactive-hover-button'
import { Settings, Download } from 'lucide-react'
import React from 'react'
import { getAuthToken, getTokenType } from '@/lib/auth'

export function GCHeader() {
  const router = useRouter()

  return (
    <header className="relative z-20 w-full py-4 bg-white shadow-sm">
      <div className="mx-auto max-w-7xl px-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Image
              src="/images/goc/canadaflag.png"
              alt="Canadian Flag"
              width={44}
              height={22}
              className="rounded-sm object-cover shadow-sm"
            />
            <div>
              <h1 className="text-xl font-semibold text-gray-900">Government of Canada</h1>
              <p className="text-sm font-medium text-gray-600">AI Assistant Portal</p>
            </div>
          </div>

          <InteractiveHoverButton
            onClick={() => {
              try {
                localStorage.removeItem('access_token')
              } catch {}
              router.push('/login')
            }}
            className="border-gray-200/60 bg-white/90 text-sm text-gray-700 backdrop-blur-sm hover:border-gray-300 hover:bg-white hover:shadow-md"
          >
            Sign out
          </InteractiveHoverButton>
        </div>
      </div>
    </header>
  )
}

type SRHeaderProps = {
  title: string
  srName?: string
  showSettings?: boolean
  showExport?: boolean
  showBack?: boolean
  backHref?: string
  backLabel?: string
  // optional node to render on the right (e.g., model selector)
  right?: React.ReactNode
}

export function SRHeader({
  title,
  srName = 'None',
  showSettings = false,
  showExport = false,
  showBack = true,
  backHref = '/can-sr',
  backLabel = 'Back to Review',
  right,
}: SRHeaderProps) {
  const router = useRouter()

  const handleExport = async () => {
    try {
      const url = new URL(window.location.href)
      const srId = url.searchParams.get('sr_id')
      if (!srId) {
        alert('Missing sr_id in URL')
        return
      }

      const token = getAuthToken()
      const tokenType = getTokenType()
      if (!token) {
        alert('You must be logged in to export citations')
        return
      }

      const res = await fetch(
        `/api/can-sr/citations/list?action=export&sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'GET',
          headers: {
            Authorization: `${tokenType} ${token}`,
          },
        },
      )

      if (!res.ok) {
        const errText = await res.text().catch(() => '')
        throw new Error(errText || `Export failed (${res.status})`)
      }

      const blob = await res.blob()
      const filename = `sr_${srName}_citations.csv`
      const blobUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(blobUrl)
    } catch (e: any) {
      console.error('Export error:', e)
      alert(e?.message || 'Export failed')
    }
  }

  return (
    <header className="relative border-b border-gray-200 bg-white shadow-sm">
      <div className="mx-auto max-w-4xl px-6">
        <div className="relative flex h-14 items-center">
          {/* Left: optional back button */}
          {showBack ? (
            <div
              onClick={() => router.push(backHref)}
              style={{ cursor: 'pointer' }}
              className="flex items-center space-x-3"
            >
              <BackButton />
              <span className="text-sm font-medium text-gray-900">{backLabel}</span>
            </div>
          ) : (
            <div />
          )}

          {/* Center: title */}
          <div className="absolute inset-x-0 flex justify-center pointer-events-none">
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          </div>

          {/* Right: optional controls */}
          <div className="ml-auto flex items-center space-x-3">
            {showSettings ? (
              <button
                type="button"
                onClick={() => {
                  alert('Settings (placeholder)')
                }}
                className="hidden items-center space-x-2 rounded-md border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 md:flex"
              >
                <Settings className="h-4 w-4 text-gray-600" />
                <span>Settings</span>
              </button>
            ) : null}

            {showExport ? (
              <button
                type="button"
                onClick={() => {
                  handleExport()
                }}
                className="hidden items-center space-x-2 rounded-md border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 md:flex"
              >
                <Download className="h-4 w-4 text-gray-600" />
                <span>Export</span>
              </button>
            ) : null}

            {/* allow callers to inject a right-side node such as the model selector */}
            {right ? right : <div />}
          </div>
        </div>
      </div>
    </header>
  )
}

export default GCHeader
