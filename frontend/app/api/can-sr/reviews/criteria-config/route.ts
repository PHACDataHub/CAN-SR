import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

function target(request: NextRequest, suffix = '') {
  const srId = request.nextUrl.searchParams.get('sr_id')
  if (!srId) return null
  return `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/criteria-config${suffix}`
}

async function auth(request: NextRequest) {
  return request.headers.get('authorization')
}

export async function GET(request: NextRequest) {
  const downloadYaml = request.nextUrl.searchParams.get('download') === 'yaml'
  const url = target(request, downloadYaml ? '/yaml' : '')
  const authorization = await auth(request)
  if (!url) return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  const response = await fetch(url, { headers: { Authorization: authorization } })
  if (downloadYaml) {
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'text/yaml; charset=utf-8' },
    })
  }
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status })
}

export async function PUT(request: NextRequest) {
  const url = target(request)
  const authorization = await auth(request)
  if (!url) return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  const response = await fetch(url, {
    method: 'PUT',
    headers: { Authorization: authorization, 'Content-Type': 'application/json' },
    body: JSON.stringify(await request.json()),
  })
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status })
}

export async function POST(request: NextRequest) {
  const operation = request.nextUrl.searchParams.get('operation')
  const suffix = operation === 'import-yaml' ? '/import-yaml' : '/validate'
  const url = target(request, suffix)
  const authorization = await auth(request)
  if (!url) return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
  if (!authorization) return NextResponse.json({ error: 'Authorization header is required' }, { status: 401 })
  const response = await fetch(url, {
    method: 'POST',
    headers: { Authorization: authorization, 'Content-Type': 'application/json' },
    body: JSON.stringify(await request.json()),
  })
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status })
}
