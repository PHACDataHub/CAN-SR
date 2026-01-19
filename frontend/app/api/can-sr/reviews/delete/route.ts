import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for delete-related operations on systematic reviews.
 *
 * Routes handled:
 * - DELETE /api/can-sr/reviews/delete?sr_id=...            -> soft delete SR (forward to BACKEND_URL/api/sr/{sr_id})
 * - DELETE /api/can-sr/reviews/delete?sr_id=...&hard=1     -> hard delete SR (forward to BACKEND_URL/api/sr/{sr_id}/hard)
 * - POST   /api/can-sr/reviews/delete?sr_id=...&undelete=1 -> undelete (restore) SR (forward to BACKEND_URL/api/sr/{sr_id}/undelete)
 *
 * Notes:
 * - Authentication cookies are forwarded to the backend via the cookie header.
 * - Backend is the source of truth for permission checks (owner vs member).
 */

export async function DELETE(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const hard = params.get('hard')

    if (!srId) {
      return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
    }

    if (hard) {
      // Hard delete endpoint
      const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/hard`
      const authHeader = request.headers.get('authorization')
      const headers: Record<string, string> = {}
      if (authHeader) {
        headers['Authorization'] = authHeader
      } else {
        headers['cookie'] = request.headers.get('cookie') || ''
      }

      const res = await fetch(url, {
        method: 'DELETE',
        headers,
      })
      const data = await res.json().catch(() => ({}))
      return NextResponse.json(data, { status: res.status })
    }

    // Soft delete
    const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}`
    const authHeader = request.headers.get('authorization')
    const headers: Record<string, string> = {}
    if (authHeader) {
      headers['Authorization'] = authHeader
    } else {
      headers['cookie'] = request.headers.get('cookie') || ''
    }

    const res = await fetch(url, {
      method: 'DELETE',
      headers,
    })
    const data = await res.json().catch(() => ({}))
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('SR delete API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function POST(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const undelete = params.get('undelete')

    if (!srId) {
      return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
    }

    if (!undelete) {
      return NextResponse.json(
        { error: "To undelete provide query param 'undelete=1' on POST" },
        { status: 400 },
      )
    }

    const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/undelete`
    const authHeader = request.headers.get('authorization')
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (authHeader) {
      headers['Authorization'] = authHeader
    } else {
      headers['cookie'] = request.headers.get('cookie') || ''
    }

    const res = await fetch(url, {
      method: 'POST',
      headers,
    })
    const data = await res.json().catch(() => ({}))
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('SR undelete API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
