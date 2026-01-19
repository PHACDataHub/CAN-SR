import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for viewing/listing systematic reviews for the current user.
 *
 * Routes handled:
 * - GET /api/can-sr/reviews/list  -> lists SRs the current user has access to (forwards to BACKEND_URL/api/sr/mine)
 *
 * Notes:
 * - Authentication cookies are forwarded to the backend via the cookie header.
 */

export async function GET(request: NextRequest) {
  try {
    const url = `${BACKEND_URL}/api/sr/mine`
    const authHeader = request.headers.get('authorization')
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
      method: 'GET',
      headers,
    })
    const data = await res.json().catch(() => ([]))
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('SR view (mine) GET API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
