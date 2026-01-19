import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy for parameter extraction actions.
 *
 * Routes handled:
 * - POST /api/can-sr/extract?action=extract-parameter&sr_id=<sr_id>&citation_id=<id>
 *    -> forwards to: POST {BACKEND_URL}/api/extract/{sr_id}/citations/{citation_id}/extract-parameter
 *
 * - POST /api/can-sr/extract?action=human-extract-parameter&sr_id=<sr_id>&citation_id=<id>
 *    -> forwards to: POST {BACKEND_URL}/api/extract/{sr_id}/citations/{citation_id}/human-extract-parameter
 *
 * Authentication: forwards Authorization header for backend calls.
 */

export async function OPTIONS() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    },
  })
}

export async function POST(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const citationId = params.get('citation_id')
    const action = params.get('action')

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

    let backendUrl: string | null = null
    if (action === 'extract-parameter') {
      backendUrl = `${BACKEND_URL}/api/extract/${encodeURIComponent(
        srId,
      )}/citations/${encodeURIComponent(citationId)}/extract-parameter`
    } else if (action === 'human-extract-parameter') {
      backendUrl = `${BACKEND_URL}/api/extract/${encodeURIComponent(
        srId,
      )}/citations/${encodeURIComponent(citationId)}/human-extract-parameter`
    } else {
      return NextResponse.json(
        { error: "Unsupported or missing 'action' parameter" },
        { status: 400 },
      )
    }

    let body: any = null
    try {
      body = await request.json()
    } catch {
      // If no JSON body provided, keep null
      body = null
    }

    const res = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        Authorization: authHeader,
        'Content-Type': 'application/json',
      },
      body: body ? JSON.stringify(body) : null,
    })

    // Try to return backend JSON as-is
    const text = await res.text().catch(() => '')
    let json: any = null
    try {
      json = text ? JSON.parse(text) : {}
    } catch {
      // if non-JSON, wrap it
      json = { detail: text || null }
    }
    return NextResponse.json(json, { status: res.status })
  } catch (err: any) {
    console.error('Parameter extract proxy POST error:', err)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 },
    )
  }
}
