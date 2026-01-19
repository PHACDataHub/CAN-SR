// Authentication utilities for the frontend

export interface User {
  id: string
  email: string
  full_name: string
  is_active: boolean
  is_superuser: boolean
  created_at: string
  last_login?: string
}

export interface AuthTokens {
  access_token: string
  token_type: string
}

// Token management
export const getAuthToken = (): string | null => {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('access_token')
}

export const getTokenType = (): string => {
  if (typeof window === 'undefined') return 'Bearer'
  return localStorage.getItem('token_type') || 'Bearer'
}

export const setAuthTokens = (tokens: AuthTokens): void => {
  if (typeof window === 'undefined') return
  localStorage.setItem('access_token', tokens.access_token)
  localStorage.setItem('token_type', tokens.token_type)
  localStorage.setItem('isLoggedIn', 'true')
}

export const clearAuthTokens = (): void => {
  if (typeof window === 'undefined') return
  localStorage.removeItem('access_token')
  localStorage.removeItem('token_type')
  localStorage.removeItem('isLoggedIn')
}

export const isAuthenticated = (): boolean => {
  if (typeof window === 'undefined') return false
  const token = getAuthToken()
  return !!token
}

// API request helper with authentication
export const authenticatedFetch = async (
  url: string,
  options: RequestInit = {},
): Promise<Response> => {
  const token = getAuthToken()
  const tokenType = getTokenType()

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  if (token) {
    ;(headers as Record<string, string>)['Authorization'] =
      `${tokenType} ${token}`
  }

  return fetch(url, {
    ...options,
    headers,
  })
}

// Get current user info
export const getCurrentUser = async (): Promise<User | null> => {
  try {
    const response = await authenticatedFetch('/api/auth/me')

    if (!response.ok) {
      throw new Error('Failed to get user info')
    }

    const data = await response.json()
    return data.user
  } catch (error) {
    console.error('Error getting current user:', error)
    return null
  }
}

// Logout function
export const logout = async (): Promise<void> => {
  try {
    await authenticatedFetch('/api/auth/logout', {
      method: 'POST',
    })
  } catch (error) {
    console.error('Error during logout:', error)
  } finally {
    clearAuthTokens()
  }
}
