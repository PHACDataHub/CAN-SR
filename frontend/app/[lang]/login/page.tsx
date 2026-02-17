'use client'

import { useState, useEffect } from 'react'
import Image from 'next/image'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Eye, EyeOff } from 'lucide-react'
import { API_ENDPOINTS } from '@/lib/config'
import { useDictionary } from '../DictionaryProvider'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const router = useRouter()
  const dict = useDictionary()

  // Get current language to keep language when navigating
  const { lang } = useParams<{ lang: string }>();

  // Check if user is already logged in
  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (token) {
      console.log('Login page: Token found, redirecting to CAN-SR')
      router.push(`/${lang}/can-sr`)
    }
  }, [router])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError('')

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Login failed')
      }

      // Store token and user info
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('token_type', data.token_type)
      localStorage.setItem('isLoggedIn', 'true')

      console.log('Login successful, tokens stored, redirecting to CAN-SR...')

      // Small delay to ensure localStorage is written
      setTimeout(() => {
        router.push(`/${lang}/can-sr`)
      }, 100)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen overflow-hidden">
      {/* Left side - Health Canada Image (reduced overlay opacity) */}
      <div className="relative hidden lg:block lg:w-3/5">
        <div className="absolute inset-0 z-10 bg-gradient-to-t from-black/30 to-transparent" />
        <Image
          src="/images/backgrounds/homepage.jpg"
          alt="Health Canada Building"
          fill
          className="object-cover"
          priority
        />
      </div>

      {/* Right side - Login Form */}
      <div className="flex w-full items-center justify-center overflow-y-auto bg-white p-6 md:p-10 lg:w-2/5">
        <div className="w-full max-w-md">
          <div className="mb-8 text-center">
            <h2 className="text-3xl font-bold text-gray-900">
              { dict.login.formTitle }
            </h2>
          </div>

          {error && (
            <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm">
              <p className="text-sm font-medium text-red-600">{error}</p>
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-6">
            <div className="space-y-2">
              <Label
                htmlFor="email"
                className="text-sm font-medium text-gray-700"
              >
                {dict.common.email}
              </Label>
              <Input
                id="email"
                type="email"
                className="focus:ring-opacity-50 w-full rounded-lg border border-gray-300 bg-white p-3 shadow-sm transition-all duration-200 focus:border-blue-500 focus:ring focus:ring-blue-200"
                placeholder={dict.login.emailPlaceholder}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label
                  htmlFor="password"
                  className="text-sm font-medium text-gray-700"
                >
                  {dict.common.password}
                </Label>
                <Link
                  href="#"
                  className="text-sm font-medium text-blue-600 transition-colors hover:text-blue-800"
                >
                  {dict.common.forgotPassword}
                </Link>
              </div>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  className="focus:ring-opacity-50 w-full rounded-lg border border-gray-300 bg-white p-3 pr-10 shadow-sm transition-all duration-200 focus:border-blue-500 focus:ring focus:ring-blue-200"
                  placeholder={dict.login.passwordPlaceholder}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? (
                    <EyeOff className="h-5 w-5" />
                  ) : (
                    <Eye className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>
            <div className='flex gap-3'>
              <Button
                type="submit"
                className="flex-1 w-full rounded-lg bg-blue-600 py-3 font-medium text-white transition-all duration-200 hover:bg-blue-700 focus:ring-4 focus:ring-blue-200 focus:outline-none"
                disabled={isLoading}
              >
                {isLoading ? dict.login.signingIn : dict.common.signIn}
              </Button>

              <Button
                className="flex-1 rounded-lg bg-blue-600 py-3 font-medium text-white transition-all duration-200 hover:bg-blue-700 focus:ring-4 focus:ring-blue-200 focus:outline-none"
                onClick={() => { window.location.href = `${API_ENDPOINTS.AUTH.MICROSOFT_SSO}?lang=${lang}`}}
                type="button"
              >
                <div className='flex items-center gap-1'>
                  <svg xmlns="http://www.w3.org/2000/svg" width="21" height="21" viewBox="0 0 21 21"><title>MS-SymbolLockup</title><rect x="1" y="1" width="9" height="9" fill="#f25022" /><rect x="1" y="11" width="9" height="9" fill="#00a4ef" /><rect x="11" y="1" width="9" height="9" fill="#7fba00" /><rect x="11" y="11" width="9" height="9" fill="#ffb900" /></svg>
                  <p>{dict.common.signInWith}</p>
                </div>
              </Button>
            </div>
          </form>

          <div className="mt-8 text-center">
            <p className="text-sm text-gray-600">
              {dict.login.noAccount}{' '}
              <Link
                href={`/${lang}/register`}
                className="font-medium text-blue-600 transition-colors hover:text-blue-800"
              >
                {dict.login.registerHere}
              </Link>
            </p>
          </div>

          <div className="mt-10 text-center text-xs text-gray-500">
            <p>
              © {new Date().getFullYear()} {dict.common.copyright}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
