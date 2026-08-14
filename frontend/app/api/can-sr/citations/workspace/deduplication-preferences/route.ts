import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

async function proxy(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId)
    return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authorization)
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  const response = await fetch(
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/workspace/deduplication-preferences`,
    {
      method: request.method,
      headers: {
        Authorization: authorization,
        ...(request.method === 'PUT'
          ? { 'Content-Type': 'application/json' }
          : {}),
      },
      body: request.method === 'PUT' ? await request.text() : undefined,
    },
  )
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  })
}

export async function GET(request: NextRequest) {
  return proxy(request)
}
export async function PUT(request: NextRequest) {
  return proxy(request)
}
