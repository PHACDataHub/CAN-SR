import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for creating systematic reviews and visibility actions (undelete / fetch mine / fetch single)
 *
 * Routes handled:
 * - POST    /api/can-sr/reviews/create                              -> create SR (multipart or JSON)
 * - GET     /api/can-sr/reviews/create?sr_id=                       -> get single SR by id 
 * - GET     /api/can-sr/reviews/create?sr_id=...?criteria_parsed=1  -> get single SR criteria by id 
 *
 * Notes:
 * - For file uploads, send multipart/form-data to this route; it will forward FormData to backend.
 * - Authentication cookies are forwarded to the backend via the cookie header.
 */

async function forwardJson(url: string, request: NextRequest) {
  const body = await request.json()
  const authHeader = request.headers.get('authorization')
  if (!authHeader) {
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: authHeader,
  }

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  return NextResponse.json(data, { status: res.status })
}

async function forwardFormData(url: string, request: NextRequest) {
  // Read incoming FormData and forward to backend
  const formData = await request.formData()
  const fd = new FormData()
  for (const [key, value] of formData.entries()) {
    fd.append(key, value as any)
  }

  const authHeader = request.headers.get('authorization')
  if (!authHeader) {
    return NextResponse.json(
      { error: 'Authorization header is required' },
      { status: 401 },
    )
  }
  const headers: Record<string, string> = {
    Authorization: authHeader,
  }

  const res = await fetch(url, {
    method: 'POST',
    // Do not set Content-Type; fetch will set the multipart boundary automatically
    headers,
    body: fd as any,
  })
  const data = await res.json().catch(() => ({}))
  return NextResponse.json(data, { status: res.status })
}

export async function POST(request: NextRequest) {
  try {
    const url = `${BACKEND_URL}/api/sr/create`
    const contentType = request.headers.get('content-type') || ''
    if (contentType.includes('multipart/form-data')) {
      return await forwardFormData(url, request)
    } else {
      // assume JSON body with { name, description, criteria_yaml } or similar
      return await forwardJson(url, request)
    }
  } catch (error) {
    console.error('SR create API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function GET(request: NextRequest) {
  try {
    // Get the authorization header
    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }
    
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const criteriaParsed = params.get('criteria_parsed')

    if (srId && criteriaParsed) {
      // Fetch parsed criteria for SR
      const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/criteria_parsed`

      const authHeader = request.headers.get('authorization')
      if (!authHeader) {
        return NextResponse.json(
          { error: 'Authorization header is required' },
          { status: 401 },
        )
      }
      const headers: Record<string, string> = {
        Authorization: authHeader,
      }

      const res = await fetch(url, {
        method: 'GET',
        headers,
      })
      const data = await res.json().catch(() => ({}))
      return NextResponse.json(data, { status: res.status })
    }

    if (srId) {
      // Fetch single SR
      const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}`

      const authHeader = request.headers.get('authorization')
      if (!authHeader) {
        return NextResponse.json(
          { error: 'Authorization header is required' },
          { status: 401 },
        )
      }

      const res = await fetch(url, {
        method: 'GET',
        headers: {
          Authorization: authHeader,
        },
      })
      const data = await res.json().catch(() => ({}))
      return NextResponse.json(data, { status: res.status })
    }

    return NextResponse.json(
      { error: "No sr_id provided." },
      { status: 400 },
    )
  } catch (error) {
    console.error('SR create GET API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
