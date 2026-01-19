import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for editing/reuploading/deleting systematic reviews
 *
 * Routes handled (via query params):
 * - PUT    /api/can-sr/reviews/edit?sr_id=...         -> update criteria (multipart or JSON)
 *
 * Notes:
 * - For criteria updates with file uploads, send multipart/form-data to this route.
 * - Authentication cookies are forwarded to the backend via the cookie header.
 */

async function forwardJsonPut(url: string, request: NextRequest) {
  const body = await request.json()
  const authHeader = request.headers.get('authorization')
  if (!authHeader) {
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  }

  const res = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: authHeader,
    },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  return NextResponse.json(data, { status: res.status })
}

async function forwardFormDataPut(url: string, request: NextRequest) {
  const formData = await request.formData()
  const fd = new FormData()
  for (const [key, value] of formData.entries()) {
    fd.append(key, value as any)
  }

  const authHeader = request.headers.get('authorization')
  if (!authHeader) {
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  }

  const res = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: authHeader,
    },
    body: fd as any,
  })
  const data = await res.json().catch(() => ({}))
  return NextResponse.json(data, { status: res.status })
}

export async function PUT(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    if (!srId) {
      return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
    }

    const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/criteria`
    const contentType = request.headers.get('content-type') || ''
    if (contentType.includes('multipart/form-data')) {
      return await forwardFormDataPut(url, request)
    } else {
      // assume JSON body with { criteria_yaml: '...' } or similar
      return await forwardJsonPut(url, request)
    }
  } catch (error) {
    console.error('SR edit PUT API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
