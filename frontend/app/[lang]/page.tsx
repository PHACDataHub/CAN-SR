'use client'

import { useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useDictionary } from './DictionaryProvider'

export default function HomePage() {
  const router = useRouter()
  const dict = useDictionary()

  // Get current language to keep language when navigating
  const { lang } = useParams<{ lang: string }>();

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      router.push(`/${lang}/login`)
      return
    }

    const tokenType = localStorage.getItem('token_type') || 'Bearer'
    fetch('/api/auth/me', {
      headers: { Authorization: `${tokenType} ${token}` },
    })
      .then((res) => {
        if (res.ok) {
          router.push(`/${lang}/can-sr`)
        } else {
          localStorage.removeItem('access_token')
          localStorage.removeItem('token_type')
          localStorage.removeItem('isLoggedIn')
          router.push(`/${lang}/login`)
        }
      })
      .catch(() => {
        localStorage.removeItem('access_token')
        localStorage.removeItem('token_type')
        localStorage.removeItem('isLoggedIn')
        router.push(`/${lang}/login`)
      })
  }, [router, lang])

  // This is just a placeholder while the redirect happens
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="mx-auto h-12 w-12 animate-spin rounded-full border-t-2 border-b-2 border-blue-600"></div>
        <p className="mt-4 text-gray-600">{dict.common.redirecting}</p>
      </div>
    </div>
  )
}
