'use client'

import { useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useDictionary } from '../DictionaryProvider'

export default function LoginPage() {
  const router = useRouter()
  const dict = useDictionary()

  // Get current language to keep language when navigating
  const { lang } = useParams<{ lang: string }>();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const accessToken = params.get('access_token')
    const tokenType = params.get('token_type') || 'Bearer'

    if (accessToken) {
      localStorage.setItem('access_token', accessToken)
      localStorage.setItem('token_type', tokenType)
      localStorage.setItem('isLoggedIn', 'true')
      setTimeout(() => {
        router.push(`/${lang}/can-sr`)
      }, 100)
      return
    }

    const token = localStorage.getItem('access_token')
    if (token) {
      router.push(`/${lang}/can-sr`)
    }
  }, [router])
 

  return (
    <div className="flex min-h-screen overflow-hidden">
      {dict.common.loggingIn}
    </div>
  )
}
