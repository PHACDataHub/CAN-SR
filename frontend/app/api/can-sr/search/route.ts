import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'
/**
 * Frontend proxy for screening actions:
 *
 * Routes handled:
 * - POST /api/can-sr/search&sr_id=<sr_id>
 *
 * Forwards request to backend:
 * - POST {BACKEND_URL}/api/database_search/{sr_id}/search
 *
 * Authentication: forwards Authorization header if present, otherwise forwards cookie header.
 */

export async function POST(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')

    if (!srId) {
      return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
    }
    const body = await request.json().catch(() => ({}))

    const url = `${BACKEND_URL}/api/database_search/${encodeURIComponent(
      srId,
    )}/search`

    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Authorization: authHeader,
    }
    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })

    const data = await res.json().catch(() => ({}))
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Search POST API error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 },
    )
  }
}
