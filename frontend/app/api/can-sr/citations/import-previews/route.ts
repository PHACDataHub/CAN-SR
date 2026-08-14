import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function POST(request: NextRequest) {
  const srId = request.nextUrl.searchParams.get('sr_id')
  const authorization = request.headers.get('authorization')
  if (!srId)
    return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authorization)
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  const formData = await request.formData()
  const response = await fetch(
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/import-previews`,
    {
      method: 'POST',
      headers: { Authorization: authorization },
      body: formData,
    },
  )
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  })
}
