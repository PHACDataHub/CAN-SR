import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for uploading a citations CSV to create a screening DB.
 *
 * Route handled:
 * - POST /api/can-sr/citations/upload?sr_id=<sr_id>
 *
 * Forwards request to backend:
 * POST {BACKEND_URL}/api/citations/{sr_id}/upload-citations
 *
 * Accepts multipart/form-data with a 'file' field. Forwards authentication via
 * Authorization header (if present) or cookie header.
 */

export async function POST(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')

    if (!srId) {
      return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
    }

    const contentType = request.headers.get('content-type') || ''
    if (!contentType.includes('multipart/form-data')) {
      return NextResponse.json(
        { error: 'Content-Type must be multipart/form-data with a file field' },
        { status: 400 },
      )
    }

    const authHeader = request.headers.get('authorization')
    const formData = await request.formData()
    const file = formData.get('file') as File

    if (!file || !file.name) {
      return NextResponse.json({ error: 'File is required' }, { status: 400 })
    }

    // Basic validation: allow CSV or RIS uploads
    const lower = file.name.toLowerCase()
    const isAllowed =
      lower.endsWith('.csv') || lower.endsWith('.ris') || lower.endsWith('.txt')
    if (!isAllowed) {
      // allow backend to enforce stricter checks (some exports have odd extensions)
    }

    // Forward form data to backend
    const backendForm = new FormData()
    backendForm.append('file', file)

    const url = `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/upload-citations`

    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }
    const headers: Record<string, string> = {
      Authorization: authHeader,
    }

    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: backendForm as any,
    })

    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      return NextResponse.json(
        { error: data.detail || data || 'Upload failed' },
        { status: res.status },
      )
    }

    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Citations upload POST API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
