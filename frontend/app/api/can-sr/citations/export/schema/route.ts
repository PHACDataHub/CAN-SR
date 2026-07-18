import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function GET(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId) return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  try {
    const response = await fetch(
      `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/export-schema`,
      { headers: { Authorization: authorization }, cache: 'no-store' },
    )
    const data = await response.json().catch(() => ({ error: 'Invalid backend response' }))
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Citation export schema proxy error:', error)
    return NextResponse.json({ error: 'Unable to load export options' }, { status: 502 })
  }
}