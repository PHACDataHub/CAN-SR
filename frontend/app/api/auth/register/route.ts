import { NextRequest, NextResponse } from 'next/server'
import { API_ENDPOINTS } from '@/lib/config'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { email, full_name, password, confirm_password } = body

    // Validate input
    if (!email || !full_name || !password || !confirm_password) {
      return NextResponse.json(
        { error: 'All fields are required' },
        { status: 400 },
      )
    }

    if (password !== confirm_password) {
      return NextResponse.json(
        { error: 'Passwords do not match' },
        { status: 400 },
      )
    }

    if (password.length < 8) {
      return NextResponse.json(
        { error: 'Password must be at least 8 characters long' },
        { status: 400 },
      )
    }

    // Validate password strength
    if (!/[A-Z]/.test(password)) {
      return NextResponse.json(
        { error: 'Password must contain at least one uppercase letter' },
        { status: 400 },
      )
    }

    if (!/[!@#$%^&*(),.?":{}|<>]/.test(password)) {
      return NextResponse.json(
        { error: 'Password must contain at least one special character' },
        { status: 400 },
      )
    }

    // Call backend register API
    const response = await fetch(API_ENDPOINTS.AUTH.REGISTER, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email,
        full_name,
        password,
        confirm_password,
      }),
    })

    const data = await response.json()

    if (!response.ok) {
      return NextResponse.json(
        { error: data.detail || 'Registration failed' },
        { status: response.status },
      )
    }

    // Return success response
    return NextResponse.json({
      success: true,
      user: {
        id: data.id,
        email: data.email,
        full_name: data.full_name,
        is_active: data.is_active,
        created_at: data.created_at,
      },
      message: 'Registration successful',
    })
  } catch (error) {
    console.error('Register API error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 },
    )
  }
}
