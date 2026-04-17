import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy: GET /api/can-sr/screen/citation-ids?sr_id=<sr>&step=l1|l2&filter=all|needs|validated|unvalidated|not_screened
 *   -> GET {BACKEND_URL}/api/screen/citation-ids?sr_id=...&step=...&filter=...
 */

export async function GET(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const step = params.get('step') || 'l1'
    const filter = params.get('filter') || 'all'

    if (!srId) {
      return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
    }

    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }

    const url = new URL(`${BACKEND_URL}/api/screen/citation-ids`)
    url.searchParams.set('sr_id', srId)
    url.searchParams.set('step', step)
    url.searchParams.set('filter', filter)

    const res = await fetch(url.toString(), {
      method: 'GET',
      headers: {
        Authorization: authHeader,
      },
    })

    const text = await res.text().catch(() => '')
    let json: any = null
    try {
      json = text ? JSON.parse(text) : {}
    } catch {
      json = { detail: text || null }
    }

    return NextResponse.json(json, { status: res.status })
  } catch (err: any) {
    console.error('screen citation-ids proxy GET error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
