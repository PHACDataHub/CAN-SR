import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  const srId = params.get('sr_id')
  const authHeader = request.headers.get('authorization')
  if (!srId)
    return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authHeader)
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )

  try {
    const url = new URL(
      `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/workspace`,
    )
    for (const key of [
      'page',
      'page_size',
      'search',
      'sort',
      'direction',
      'columns',
      'filters',
      'duplicate_status',
    ]) {
      const value = params.get(key)
      if (value) url.searchParams.set(key, value)
    }
    const response = await fetch(url.toString(), {
      headers: { Authorization: authHeader },
    })
    const text = await response.text()
    let body: unknown
    try {
      body = text ? JSON.parse(text) : {}
    } catch {
      body = { detail: text || null }
    }
    return NextResponse.json(body, { status: response.status })
  } catch (error) {
    console.error('Citations workspace proxy GET error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 },
    )
  }
}

export async function DELETE(request: NextRequest) {
  const params = request.nextUrl.searchParams
  const srId = params.get('sr_id')
  const authHeader = request.headers.get('authorization')
  if (!srId)
    return NextResponse.json({ error: 'sr_id is required' }, { status: 400 })
  if (!authHeader)
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  const response = await fetch(
    `${BACKEND_URL}/api/cite/${encodeURIComponent(srId)}/citations/workspace`,
    {
      method: 'DELETE',
      headers: {
        Authorization: authHeader,
        'Content-Type': 'application/json',
      },
      body: await request.text(),
    },
  )
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  })
}
