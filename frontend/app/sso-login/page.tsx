'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function LoginPage() {

  const router = useRouter()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const accessToken = params.get('access_token')
    const tokenType = params.get('token_type') || 'Bearer'

    if (accessToken) {
      localStorage.setItem('access_token', accessToken)
      localStorage.setItem('token_type', tokenType)
      localStorage.setItem('isLoggedIn', 'true')
      setTimeout(() => {
        router.push('/can-sr')
      }, 100)
      return
    }

    const token = localStorage.getItem('access_token')
    if (token) {
      router.push('/can-sr')
    }
  }, [router])
 

  return (
    <div className="flex min-h-screen overflow-hidden">
      Logging in...
    </div>
  )
}
