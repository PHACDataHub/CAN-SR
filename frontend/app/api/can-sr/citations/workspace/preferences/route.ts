import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

async function proxy(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId || !authorization) {
    return NextResponse.json({ error: !srId ? 'sr_id is required' : 'Authorization header is required' }, { status: !srId ? 400 : 401 })
  }
  try {
    const response = await fetch(`${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/workspace/preferences`, {
      method: request.method,
      headers: { Authorization: authorization, ...(request.method === 'PUT' ? { 'Content-Type': 'application/json' } : {}) },
      body: request.method === 'PUT' ? await request.text() : undefined,
    })
    const text = await response.text()
    let body: unknown
    try { body = text ? JSON.parse(text) : {} } catch { body = { detail: text || null } }
    return NextResponse.json(body, { status: response.status })
  } catch (error) {
    console.error('Citations workspace preferences proxy error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export const GET = proxy
export const PUT = proxy
