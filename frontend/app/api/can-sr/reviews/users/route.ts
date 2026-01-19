import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for managing users on a systematic review
 *
 * Routes handled:
 * - POST /api/can-sr/reviews/users?action=add&sr_id=...    -> add user (body: { user_email?, user_id? })
 * - POST /api/can-sr/reviews/users?action=remove&sr_id=... -> remove user (body: { user_email?, user_id? })
 *
 * Notes:
 * - Request body must be JSON with either user_email or user_id present.
 * - This proxy requires an Authorization header and will forward it to the backend.
 * - Follows the pattern used in frontend/app/api/can-sr/reviews/create/route.ts (do not use cookies).
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

export async function POST(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const action = (params.get('action') || '').toLowerCase()

    if (!srId) {
      return NextResponse.json({ error: 'sr_id query parameter is required' }, { status: 400 })
    }

    if (!action || (action !== 'add' && action !== 'remove')) {
      return NextResponse.json(
        { error: "query parameter 'action' is required and must be either 'add' or 'remove'" },
        { status: 400 },
      )
    }

    const url =
      action === 'add'
        ? `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/add-user`
        : `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/remove-user`

    // Expect JSON body with either { user_email } or { user_id }
    return await forwardJson(url, request)
  } catch (error) {
    console.error('SR users POST API error:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
