'use client'

import { useDictionary } from '@/app/[lang]/DictionaryProvider'

export interface SRCostSummary {
  sr_id: string
  currency: string
  totals: {
    l1: number
    l2: number
    extraction?: number
    other: number
    grand_total: number
  }
  breakdown: Record<string, number>
}

interface CostMetaProps {
  loading: boolean
  error?: string | null
  amount?: number
  currency?: string
}

export function formatCurrency(amount: number, currency?: string): string {
  const normalizedCurrency = String(currency || 'USD').trim().toUpperCase() || 'USD'
  return new Intl.NumberFormat('en-CA', {
    style: 'currency',
    currency: normalizedCurrency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount)
}

export default function CostMeta({ loading, error, amount, currency }: CostMetaProps) {
  const dict = useDictionary()

  if (loading) {
    return (
      <p className="text-sm text-emerald-800">
        {dict.common.totalCost}: <span className="font-medium">{dict.common.loading}</span>
      </p>
    )
  }

  if (error) {
    return <p className="text-sm text-amber-800">{dict.common.totalCostUnavailable}</p>
  }

  return (
    <p className="text-sm text-emerald-800">
      {dict.common.totalCost}: <span className="font-medium">{formatCurrency(amount || 0, currency)}</span>
    </p>
  )
}
