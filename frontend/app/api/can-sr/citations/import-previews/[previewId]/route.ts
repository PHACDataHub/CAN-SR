import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

async function forward(request: NextRequest, method: 'GET' | 'DELETE') {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  const previewId = request.nextUrl.pathname.split('/').pop()
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
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/import-previews/${encodeURIComponent(previewId)}`,
    {
      method,
      headers: { Authorization: authorization },
    },
  )
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  })
}

export async function GET(request: NextRequest) {
  return forward(request, 'GET')
}
export async function DELETE(request: NextRequest) {
  return forward(request, 'DELETE')
}
