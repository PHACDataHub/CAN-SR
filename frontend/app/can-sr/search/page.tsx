'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { ModelSelector } from '@/components/chat'
import React, { useEffect, useState } from 'react'
import { getAuthToken, getTokenType } from '@/lib/auth'

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const tokenType = getTokenType()
  return token
    ? { Authorization: `${tokenType} ${token}` }
    : ({} as Record<string, string>)
}

export default function Search() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const [selectedModel, setSelectedModel] = useState('gpt-4o')
  const databases = ['Pubmed', 'Scopus', 'EuropePMC']
  const [selectedDatabase, setSelectedDatabase] = useState('')
  const [searchStrings, setSearchString] = useState<Record<string, string>>({})

  if (!srId) {
    router.replace('/can-sr')
    return
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedDatabase) {
      alert('Please select a database')
      return
    }
    const headers = getAuthHeaders()

    const bodyPayload = {
      database: selectedDatabase,
      search_term: searchStrings[selectedDatabase],
    }
    const res = await fetch(
      `/api/can-sr/search?sr_id=${encodeURIComponent(srId)}`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(bodyPayload),
      },
    )
  }

  const handleTextChange = (database: string, value: string) => {
    setSearchString((prev) => ({ ...prev, [database]: value }))
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />

      <SRHeader
        title="Search"
        backHref={`/can-sr/sr?sr_id=${encodeURIComponent(srId)}`}
        right={
          <ModelSelector
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        }
      />
      <main className="mx-auto max-w-4xl px-6 py-10">
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="text-xl font-semibold text-gray-900">
            Select Database
          </h3>
          <p className="mt-2 text-sm text-gray-600">
            Select a database and enter a search string
          </p>

          <form
            onSubmit={handleSubmit}
            className="mt-6 flex flex-col items-center space-y-4"
          >
            {databases.map((database) => (
              <div
                key={database}
                className="mb-3 flex items-center gap-3 rounded-xl border p-3"
              >
                <input
                  type="radio"
                  name="database"
                  value={database}
                  onChange={() => setSelectedDatabase(database)}
                  className="h-4 w-4"
                />
                <label className="flex-1 font-medium text-gray-800">
                  {database}
                </label>

                <input
                  type="text"
                  placeholder="enter search string"
                  onChange={(e) => handleTextChange(database, e.target.value)}
                  className="flex-1 rounded-md border px-2 py-1 text-sm"
                />
              </div>
            ))}
            <button
              type="submit"
              disabled={!selectedDatabase}
              className="w-[80px] rounded-md bg-emerald-600 px-1 py-1 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Begin Search
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
