import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy: GET /api/can-sr/screen/agent-runs/latest?sr_id=<sr>&pipeline=title_abstract&citation_ids=1,2,3
 *   -> GET {BACKEND_URL}/api/screen/agent-runs/latest?sr_id=...&pipeline=...&citation_ids=...
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
    const pipeline = params.get('pipeline')
    const citationIds = params.get('citation_ids')

    if (!srId || !pipeline || !citationIds) {
      return NextResponse.json(
        { error: 'sr_id, pipeline, citation_ids are required' },
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

    const url = new URL(`${BACKEND_URL}/api/screen/agent-runs/latest`)
    url.searchParams.set('sr_id', srId)
    url.searchParams.set('pipeline', pipeline)
    url.searchParams.set('citation_ids', citationIds)

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
    console.error('Agent runs latest proxy GET error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
