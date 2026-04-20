import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy: POST /api/can-sr/screen/validate
 *  body: { sr_id, citation_id, step }
 *   -> POST {BACKEND_URL}/api/screen/validate
 */

export async function POST(request: NextRequest) {
  try {
    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }

    const body = await request.json().catch(() => ({}))

    const res = await fetch(`${BACKEND_URL}/api/screen/validate`, {
      method: 'POST',
      headers: {
        Authorization: authHeader,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
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
    console.error('Validate proxy POST error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
