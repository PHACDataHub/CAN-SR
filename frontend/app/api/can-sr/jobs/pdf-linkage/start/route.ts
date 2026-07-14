import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function POST(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId) return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  const response = await fetch(`${BACKEND_URL}/api/jobs/pdf-linkage/start?sr_id=${encodeURIComponent(srId)}`, {
    method: 'POST', headers: { Authorization: authorization, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pipeline_key: 'pdf_linkage',
      ...await request.json().catch(() => ({})),
    }),
  })
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status })
}