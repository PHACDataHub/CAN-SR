import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy to fetch a single citation row from backend screening DB.
 *
 * GET /api/can-sr/citations/get?sr_id=<sr_id>&citation_id=<id>
 *   - forwards to: GET {BACKEND_URL}/api/cite/{sr_id}/citations/{citation_id}
 *
 * Requires Authorization header. Returns backend JSON as-is with same status.
 */

export async function OPTIONS() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,OPTIONS',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    },
  })
}

export async function GET(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const citationId = params.get('citation_id')

    if (!srId || !citationId) {
      return NextResponse.json(
        { error: 'sr_id and citation_id are required' },
        { status: 400 },
      )
    }

    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }

    const url = `${BACKEND_URL}/api/cite/${encodeURIComponent(
      srId,
    )}/citations/${encodeURIComponent(citationId)}`

    const res = await fetch(url, {
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
    console.error('Citations get proxy GET error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
