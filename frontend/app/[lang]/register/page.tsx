'use client'

import { useState } from 'react'
import Image from 'next/image'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Eye, EyeOff } from 'lucide-react'
import { useDictionary } from '../DictionaryProvider'

export default function RegisterPage() {
  const dict = useDictionary()
  const [formData, setFormData] = useState({
    email: '',
    full_name: '',
    password: '',
    confirm_password: '',
  })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const router = useRouter()

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }))
    // Clear error when user starts typing
    if (error) setError('')
  }

  const validatePassword = (password: string): string | null => {
    if (password.length < 8) {
      return dict.register.passwordMinLength
    }
    if (!/[A-Z]/.test(password)) {
      return dict.register.passwordUppercase
    }
    if (!/[!@#$%^&*(),.?":{}|<>]/.test(password)) {
      return dict.register.passwordSpecialChar
    }
    return null
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError('')
    setSuccess('')

    // Validate password strength
    const passwordError = validatePassword(formData.password)
    if (passwordError) {
      setError(passwordError)
      setIsLoading(false)
      return
    }

    // Validate passwords match
    if (formData.password !== formData.confirm_password) {
      setError(dict.register.passwordsNoMatch)
      setIsLoading(false)
      return
    }

    try {
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Registration failed')
      }

      setSuccess(dict.register.successMessage)

      // Redirect to login page after 2 seconds
      setTimeout(() => {
        router.push('/login')
      }, 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setIsLoading(false)
    }
  }

  // Get current language to keep language when navigating
  const { lang } = useParams<{ lang: string }>();

  return (
    <div className="flex min-h-screen overflow-hidden">
      {/* Left side - Health Canada Image */}
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

      {/* Right side - Register Form */}
      <div className="flex w-full items-center justify-center overflow-y-auto bg-white p-6 md:p-10 lg:w-2/5">
        <div className="w-full max-w-md">
          <div className="mb-8 text-center">
            <h2 className="text-3xl font-bold text-gray-900">
              {dict.register.formTitle}
            </h2>
            <p className="mt-2 text-gray-600">
              {dict.register.formSubtitle}
            </p>
          </div>

          {error && (
            <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm">
              <p className="text-sm font-medium text-red-600">{error}</p>
            </div>
          )}

          {success && (
            <div className="mb-6 rounded-lg border border-green-200 bg-green-50 p-4 shadow-sm">
              <p className="text-sm font-medium text-green-600">{success}</p>
            </div>
          )}

          <form onSubmit={handleRegister} className="space-y-6">
            <div className="space-y-2">
              <Label
                htmlFor="email"
                className="text-sm font-medium text-gray-700"
              >
                {dict.common.email}
              </Label>
              <Input
                id="email"
                name="email"
                type="email"
                className="focus:ring-opacity-50 w-full rounded-lg border border-gray-300 bg-white p-3 shadow-sm transition-all duration-200 focus:border-blue-500 focus:ring focus:ring-blue-200"
                placeholder={dict.login.emailPlaceholder}
                value={formData.email}
                onChange={handleInputChange}
                required
              />
            </div>

            <div className="space-y-2">
              <Label
                htmlFor="full_name"
                className="text-sm font-medium text-gray-700"
              >
                {dict.register.fullName}
              </Label>
              <Input
                id="full_name"
                name="full_name"
                type="text"
                className="focus:ring-opacity-50 w-full rounded-lg border border-gray-300 bg-white p-3 shadow-sm transition-all duration-200 focus:border-blue-500 focus:ring focus:ring-blue-200"
                placeholder={dict.register.fullNamePlaceholder}
                value={formData.full_name}
                onChange={handleInputChange}
                required
              />
            </div>

            <div className="space-y-2">
              <Label
                htmlFor="password"
                className="text-sm font-medium text-gray-700"
              >
                {dict.common.password}
              </Label>
              <div className="relative">
                <Input
                  id="password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  className="focus:ring-opacity-50 w-full rounded-lg border border-gray-300 bg-white p-3 pr-10 shadow-sm transition-all duration-200 focus:border-blue-500 focus:ring focus:ring-blue-200"
                  placeholder={dict.login.passwordPlaceholder}
                  value={formData.password}
                  onChange={handleInputChange}
                  required
                  minLength={8}
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
              <p className="mt-1 text-xs text-gray-500">
                {dict.register.passwordRequirements}
              </p>
            </div>

            <div className="space-y-2">
              <Label
                htmlFor="confirm_password"
                className="text-sm font-medium text-gray-700"
              >
                {dict.register.confirmPassword}
              </Label>
              <div className="relative">
                <Input
                  id="confirm_password"
                  name="confirm_password"
                  type={showConfirmPassword ? 'text' : 'password'}
                  className="focus:ring-opacity-50 w-full rounded-lg border border-gray-300 bg-white p-3 pr-10 shadow-sm transition-all duration-200 focus:border-blue-500 focus:ring focus:ring-blue-200"
                  placeholder={dict.login.passwordPlaceholder}
                  value={formData.confirm_password}
                  onChange={handleInputChange}
                  required
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                >
                  {showConfirmPassword ? (
                    <EyeOff className="h-5 w-5" />
                  ) : (
                    <Eye className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>

            <Button
              type="submit"
              className="w-full rounded-lg bg-blue-600 py-3 font-medium text-white transition-all duration-200 hover:bg-blue-700 focus:ring-4 focus:ring-blue-200 focus:outline-none"
              disabled={isLoading}
            >
              {isLoading ? dict.register.creatingAccount : dict.register.createAccount}
            </Button>
          </form>

          <div className="mt-8 text-center">
            <p className="text-sm text-gray-600">
              {dict.register.haveAccount}{' '}
              <Link
                href={`/${lang}/login`}
                className="font-medium text-blue-600 transition-colors hover:text-blue-800"
              >
                {dict.register.signInHere}
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
