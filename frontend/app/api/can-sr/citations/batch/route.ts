import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy to fetch multiple citations from backend screening DB.
 *
 * GET /api/can-sr/citations/batch?sr_id=<sr_id>&ids=1,2,3
 *   - forwards to: GET {BACKEND_URL}/api/cite/{sr_id}/citations/batch?ids=1,2,3
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
    const ids = params.get('ids')
    const fields = params.get('fields')

    if (!srId || !ids) {
      return NextResponse.json(
        { error: 'sr_id and ids are required' },
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

    const url = new URL(
      `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/batch`,
    )
    url.searchParams.set('ids', ids)
    if (fields) url.searchParams.set('fields', fields)

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
    console.error('Citations batch proxy GET error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
