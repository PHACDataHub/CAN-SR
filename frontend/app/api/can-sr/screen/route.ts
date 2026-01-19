import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for screening actions:
 *
 * Routes handled:
 * - POST /api/can-sr/screen?action=classify&sr_id=<sr_id>&citation_id=<id>
 * - POST /api/can-sr/screen?action=human_classify&sr_id=<sr_id>&citation_id=<id>
 *
 * Forwards request to backend:
 * - POST {BACKEND_URL}/api/screen/{sr_id}/citations/{citation_id}/classify
 * - POST {BACKEND_URL}/api/screen/{sr_id}/citations/{citation_id}/human_classify
 *
 * Authentication: forwards Authorization header if present, otherwise forwards cookie header.
 */

export async function POST(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const citationId = params.get('citation_id')
    const action = params.get('action') // expected 'classify' or 'human_classify'

    if (!srId || !citationId || !action) {
      return NextResponse.json(
        { error: 'sr_id, citation_id and action are required' },
        { status: 400 },
      )
    }

    if (action !== 'classify' && action !== 'human_classify') {
      return NextResponse.json(
        { error: "action must be 'classify' or 'human_classify'" },
        { status: 400 },
      )
    }

    const body = await request.json().catch(() => ({}))

    const url = `${BACKEND_URL}/api/screen/${encodeURIComponent(
      srId,
    )}/citations/${encodeURIComponent(citationId)}/${action}`

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
    console.error('Screen POST API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
