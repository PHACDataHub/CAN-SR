import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

export async function GET(request: NextRequest) {
    try {
        const authHeader = request.headers.get('authorization')
        if (!authHeader) {
            return NextResponse.json(
                { error: 'Authorization header is required' },
                { status: 401 },
            )
        }

        const srId = request.nextUrl.searchParams.get('sr_id')
        if (!srId) {
            return NextResponse.json(
                { error: 'sr_id is required' },
                { status: 400 },
            )
        }

        const url = `${BACKEND_URL}/api/sr/${encodeURIComponent(srId)}/costs`

        const res = await fetch(url, {
            method: 'GET',
            headers: {
                Authorization: authHeader,
            },
            cache: 'no-store',
        })

        const data = await res.json().catch(() => ({}))
        return NextResponse.json(data, { status: res.status })
    } catch (error) {
        console.error('SR costs proxy GET error:', error)
        return NextResponse.json(
            { error: 'Internal server error' },
            { status: 500 }
        )
    }
}
