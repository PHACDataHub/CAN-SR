import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Proxy: POST /api/can-sr/screen/fulltext/run
 *   -> POST {BACKEND_URL}/api/screen/fulltext/run
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

    const url = `${BACKEND_URL}/api/screen/fulltext/run`
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: authHeader,
      },
      body: JSON.stringify(body),
    })

    const data = await res.json().catch(() => ({}))
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    console.error('fulltext/run proxy POST error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
