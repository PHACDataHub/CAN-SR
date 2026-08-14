import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function PUT(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  const previewId = request.nextUrl.pathname.split('/').slice(-2, -1)[0]
  if (!srId || !previewId)
    return NextResponse.json(
      { error: 'sr_id and preview id are required' },
      { status: 400 },
    )
  if (!authorization)
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  const response = await fetch(
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/import-previews/${encodeURIComponent(previewId)}/mapping`,
    {
      method: 'PUT',
      headers: {
        Authorization: authorization,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(await request.json()),
    },
  )
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  })
}
