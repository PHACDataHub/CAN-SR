'use client'

import { getAuthToken, getTokenType } from '@/lib/auth'

export type ExportDimension = { id: string; label: string; default_selected: boolean }
export type ExportItem = {
  id: string
  label: string
  default_selected: boolean
  category?: string | null
  available_dimensions?: string[] | null
}
export type ExportGroup = { id: string; label: string; dimensions: ExportDimension[]; items: ExportItem[] }
export type CitationExportSchema = { schema_version: 1; format: 'csv'; row_scopes: string[]; groups: ExportGroup[] }

function authHeaders() {
  const token = getAuthToken()
  if (!token) throw new Error('You must be logged in to export citations')
  return { Authorization: `${getTokenType()} ${token}` }
}

async function responseError(response: Response) {
  const data = await response.json().catch(() => null)
  return data?.detail || data?.error || `Export request failed (${response.status})`
}

export async function loadCitationExportSchema(srId: string): Promise<CitationExportSchema> {
  const response = await fetch(
    `/api/can-sr/citations/export/schema?sr_id=${encodeURIComponent(srId)}`,
    { headers: authHeaders() },
  )
  if (!response.ok) throw new Error(await responseError(response))
  return response.json()
}

export async function downloadCitationExport(srId: string, payload: unknown) {
  const response = await fetch(
    `/api/can-sr/citations/export?sr_id=${encodeURIComponent(srId)}`,
    {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await responseError(response))
  const disposition = response.headers.get('content-disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  const filename = match?.[1] || `sr_${srId}_citations.csv`
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}