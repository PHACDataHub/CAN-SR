'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function HomePage() {
  const router = useRouter()

  useEffect(() => {
    // Check if user is logged in
    const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true'

    if (isLoggedIn) {
      // If logged in, redirect to portal
      router.push('/portal')
    } else {
      // If not logged in, redirect to login
      router.push('/login')
    }
  }, [router])

  // This is just a placeholder while the redirect happens
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="mx-auto h-12 w-12 animate-spin rounded-full border-t-2 border-b-2 border-blue-600"></div>
        <p className="mt-4 text-gray-600">Redirecting...</p>
      </div>
    </div>
  )
}
