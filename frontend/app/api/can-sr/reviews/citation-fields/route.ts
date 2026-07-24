import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function GET(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId) return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  const response = await fetch(`${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/citation-fields`, {
    headers: { Authorization: authorization },
  })
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status })
}
