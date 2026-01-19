import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for listing citation ids for a systematic review's screening DB.
 *
 * Route handled:
 * - GET /api/can-sr/citations/list?sr_id=<sr_id>
 * - GET /api/can-sr/citations/list?action=export&sr_id=<sr_id>
 *
 * Forwards request to backend: GET {BACKEND_URL}/api/citations/{sr_id}/citations
 * Authentication cookies are forwarded via the cookie header.
 */

export async function GET(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const filter = params.get('filter')
    const action = params.get('action')

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

    // Export CSV passthrough
    if (action === 'export') {
      const url = `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/export-citations`
      const res = await fetch(url, {
        method: 'GET',
        headers: {
          Authorization: authHeader,
        },
      })

      // Pass through the CSV body as a stream. We intentionally do NOT parse JSON.
      const contentType = res.headers.get('content-type') || 'text/csv; charset=utf-8'
      const disposition = res.headers.get('content-disposition')
      return new NextResponse(res.body, {
        status: res.status,
        headers: {
          'Content-Type': contentType,
          ...(disposition ? { 'Content-Disposition': disposition } : {}),
        },
      })
    }

    let url = `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations`
    if (filter) {
      url += `?filter_step=${encodeURIComponent(filter)}`
    }

    const res = await fetch(url, {
      method: 'GET',
      headers: {
        Authorization: authHeader,
      },
    })

    // try to parse JSON, but be resilient
    const data = await res.json().catch(() => ({}))
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Citations list GET API error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 },
    )
  }
}
