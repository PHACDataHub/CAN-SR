import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function GET(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const runId = request.nextUrl.searchParams.get('run_id')
  const authorization = request.headers.get('authorization')
  if (!srId) return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!runId) return NextResponse.json({ error: 'run_id is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  const response = await fetch(
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/workspace/duplicate-runs/${encodeURIComponent(runId)}`,
    { method: 'GET', headers: { Authorization: authorization } },
  )
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status })
}

export async function POST(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId) return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  const response = await fetch(
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/workspace/duplicate-runs`,
    { method: 'POST', headers: { Authorization: authorization } },
  )
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status })
}
