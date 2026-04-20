import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy:
 *  GET /api/can-sr/reviews/critical-prompt-additions?sr_id=<sr>
 *    -> GET {BACKEND_URL}/api/sr/<sr>/critical_prompt_additions
 *  PUT /api/can-sr/reviews/critical-prompt-additions?sr_id=<sr>
 *    body: { critical_prompt_additions: {...} }
 *    -> PUT {BACKEND_URL}/api/sr/<sr>/critical_prompt_additions
 */

function authHeaders(request: NextRequest): Record<string, string> {
  const auth = request.headers.get('authorization')
  return auth ? { Authorization: auth } : {}
}

export async function GET(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    if (!srId) {
      return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
    }
    const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/critical_prompt_additions`
    const res = await fetch(url, { method: 'GET', headers: authHeaders(request) })
    const data = await res.json().catch(() => ({}))
    return NextResponse.json(data, { status: res.status })
  } catch (e) {
    console.error('critical-prompt-additions GET error:', e)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function PUT(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    if (!srId) {
      return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
    }

    const body = await request.json().catch(() => ({}))
    const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/critical_prompt_additions`
    const res = await fetch(url, {
      method: 'PUT',
      headers: {
        ...authHeaders(request),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
    const data = await res.json().catch(() => ({}))
    return NextResponse.json(data, { status: res.status })
  } catch (e) {
    console.error('critical-prompt-additions PUT error:', e)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
