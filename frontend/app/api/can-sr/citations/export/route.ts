import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function POST(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId) return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  try {
    const body = await request.text()
    const response = await fetch(
      `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/export-citations`,
      {
        method: 'POST',
        headers: { Authorization: authorization, 'Content-Type': 'application/json' },
        body,
      },
    )
    return new NextResponse(response.body, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('content-type') || 'application/json',
        ...(response.headers.get('content-disposition')
          ? { 'Content-Disposition': response.headers.get('content-disposition')! }
          : {}),
      },
    })
  } catch (error) {
    console.error('Citation export proxy error:', error)
    return NextResponse.json({ error: 'Unable to prepare export' }, { status: 502 })
  }
}