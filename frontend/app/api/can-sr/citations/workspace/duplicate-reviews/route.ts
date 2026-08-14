import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

async function forward(request: NextRequest, method: 'GET' | 'PUT') {
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
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/workspace/duplicate-reviews`,
    {
      method,
      headers: {
        Authorization: authorization,
        'Content-Type': 'application/json',
      },
      body: method === 'PUT' ? await request.text() : undefined,
    },
  )
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  })
}

export function GET(request: NextRequest) {
  return forward(request, 'GET')
}

export function PUT(request: NextRequest) {
  return forward(request, 'PUT')
}
