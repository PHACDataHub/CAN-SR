'use client'

import { useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

/** Legacy compatibility route. The protocol workspace owns configuration UI. */
export default function CanSrSetupRedirectPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')

  useEffect(() => {
    router.replace(
      srId ? `/can-sr/protocols?sr_id=${encodeURIComponent(srId)}` : '/can-sr',
    )
  }, [router, srId])

  return null
}
