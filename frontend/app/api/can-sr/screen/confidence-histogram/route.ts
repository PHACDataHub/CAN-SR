import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy: GET /api/can-sr/screen/confidence-histogram?sr_id=<sr>&step=l1|l2&bins=...
 *   -> GET {BACKEND_URL}/api/screen/confidence-histogram?sr_id=...&step=...&bins=...
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
    const step = params.get('step') || 'l1'
    const bins = params.get('bins')

    if (!srId) {
      return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
    }

    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
    }

    const url = new URL(`${BACKEND_URL}/api/screen/confidence-histogram`)
    url.searchParams.set('sr_id', srId)
    url.searchParams.set('step', step)
    if (bins) url.searchParams.set('bins', bins)

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
    console.error('screen confidence-histogram proxy GET error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
