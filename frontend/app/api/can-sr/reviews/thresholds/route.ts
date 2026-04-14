import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for SR screening thresholds.
 *
 * Routes handled:
 * - GET /api/can-sr/reviews/thresholds?sr_id=...  -> BACKEND_URL/api/sr/{sr_id}/screening_thresholds
 * - PUT /api/can-sr/reviews/thresholds?sr_id=...  -> BACKEND_URL/api/sr/{sr_id}/screening_thresholds
 */

async function forward(request: NextRequest, method: 'GET' | 'PUT') {
  const params = request.nextUrl.searchParams
  const srId = params.get('sr_id')
  if (!srId) {
    return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
  }

  const authHeader = request.headers.get('authorization')
  if (!authHeader) {
    return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  }

  const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/screening_thresholds`

  const body = method === 'PUT' ? JSON.stringify(await request.json()) : undefined

  const res = await fetch(url, {
    method,
    headers: {
      Authorization: authHeader,
      ...(method === 'PUT' ? { 'Content-Type': 'application/json' } : {}),
    },
    body,
  })

  const data = await res.json().catch(() => ({}))
  return NextResponse.json(data, { status: res.status })
}

export async function GET(request: NextRequest) {
  try {
    return await forward(request, 'GET')
  } catch (error) {
    console.error('thresholds GET API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function PUT(request: NextRequest) {
  try {
    return await forward(request, 'PUT')
  } catch (error) {
    console.error('thresholds PUT API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
