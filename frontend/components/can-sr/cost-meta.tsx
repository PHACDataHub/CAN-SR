export interface SRCostSummary {
  sr_id: string
  currency: string
  totals: {
    l1: number
    l2: number
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
  if (loading) {
    return (
      <p className="text-sm text-emerald-800">
        Total Cost: <span className="font-medium">Loading...</span>
      </p>
    )
  }

  if (error) {
    return <p className="text-sm text-amber-800">Total Cost is unavailable.</p>
  }

  return (
    <p className="text-sm text-emerald-800">
      Total Cost: <span className="font-medium">{formatCurrency(amount || 0, currency)}</span>
    </p>
  )
}
