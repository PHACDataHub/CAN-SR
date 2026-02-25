import { NextRequest, NextResponse } from 'next/server'
import { API_ENDPOINTS, HEALTH_ENDPOINTS } from '@/lib/config'

export async function GET(request: NextRequest) {
  try {

    // Call backend config API
    const response = await fetch(HEALTH_ENDPOINTS.MAIN_API, {
      method: 'GET',
    })

    const data = await response.json()

    if (!response.ok) {
      return NextResponse.json(
        { error: data.detail || 'Failed to get config' },
        { status: response.status },
      )
    }

    // Return API config
    return NextResponse.json({
      success: true,
      config: data,
    })
  } catch (error) {
    console.error('Get API config error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 },
    )
  }
}
