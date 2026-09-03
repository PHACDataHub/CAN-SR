'use client'

import { useEffect, useMemo, useState } from 'react'
import { authenticatedFetch } from '@/lib/auth'
import { type SRCostSummary } from '@/components/can-sr/cost-meta'

interface ReviewCostState {
  cost: SRCostSummary | null
  loading: boolean
  error: string | null
}

interface ReviewCostsState {
  costsById: Record<string, SRCostSummary>
  loadingById: Record<string, boolean>
  errorById: Record<string, string>
}

export interface ExtractionCitationCostSummary {
  citation_id: number
  currency?: string
  total_cost_usd?: number | null
  parameters?: Record<string, number>
}

interface ExtractionCitationCostsState {
  costsByCitationId: Record<number, ExtractionCitationCostSummary>
  loadingByCitationId: Record<number, boolean>
  errorByCitationId: Record<number, string>
}

async function fetchReviewCost(srId: string): Promise<SRCostSummary> {
  const res = await authenticatedFetch(
    `/api/can-sr/reviews/costs?sr_id=${encodeURIComponent(srId)}`,
    { cache: 'no-store' },
  )

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}))
    throw new Error(
      errBody?.detail ||
        errBody?.error ||
        `Failed to fetch costs (${res.status})`,
    )
  }

  return await res.json().catch(() => ({}))
}

async function fetchExtractionCitationCosts(
  srId: string,
  citationIds: number[],
): Promise<{ costs: ExtractionCitationCostSummary[] }> {
  const normalizedCitationIds = Array.from(
    new Set(
      citationIds
        .map((citationId) => Number(citationId))
        .filter((citationId) => Number.isFinite(citationId) && citationId > 0),
    ),
  )

  if (normalizedCitationIds.length === 0) {
    return { costs: [] }
  }

  const res = await authenticatedFetch(
    `/api/can-sr/extract?action=costs&sr_id=${encodeURIComponent(srId)}&ids=${encodeURIComponent(normalizedCitationIds.join(','))}`,
  )

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}))
    throw new Error(
      errBody?.detail ||
        errBody?.error ||
        `Failed to fetch extraction costs (${res.status})`,
    )
  }

  return await res.json().catch(() => ({}))
}

export function useReviewCost(srId: string | null | undefined, pollIntervalMs?: number): ReviewCostState {
  const [cost, setCost] = useState<SRCostSummary | null>(null)
  const [loading, setLoading] = useState<boolean>(Boolean(srId))
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!srId) {
      setCost(null)
      setLoading(false)
      setError(null)
      return
    }

    let cancelled = false

    const load = async (isInitialLoad = false) => {
      if (isInitialLoad) {
        setLoading(true)
      }

      try {
        const data = await fetchReviewCost(srId)
        if (!cancelled) {
          setCost(data)
          setError(null)
        }
      } catch (err: any) {
        console.error('Error fetching costs:', err)
        if (!cancelled) {
          setError(err?.message || 'Unable to load costs')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load(true)

    if (!pollIntervalMs || pollIntervalMs <= 0) {
      return () => {
        cancelled = true
      }
    }

    const intervalId = window.setInterval(() => {
      void load(false)
    }, pollIntervalMs)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [srId, pollIntervalMs])

  return { cost, loading, error }
}

export function useReviewCosts(reviewIds: string[]): ReviewCostsState {
  const normalizedIds = useMemo(
    () => reviewIds.map((reviewId) => String(reviewId || '').trim()).filter(Boolean),
    [reviewIds],
  )
  const normalizedIdsKey = useMemo(() => normalizedIds.join('|'), [normalizedIds])

  const [costsById, setCostsById] = useState<Record<string, SRCostSummary>>({})
  const [loadingById, setLoadingById] = useState<Record<string, boolean>>({})
  const [errorById, setErrorById] = useState<Record<string, string>>({})

  useEffect(() => {
    if (normalizedIds.length === 0) {
      setCostsById({})
      setLoadingById({})
      setErrorById({})
      return
    }

    let cancelled = false

    setLoadingById(
      normalizedIds.reduce<Record<string, boolean>>((acc, reviewId) => {
        acc[reviewId] = true
        return acc
      }, {}),
    )
    setErrorById({})

    const load = async () => {
      const results = await Promise.all(
        normalizedIds.map(async (reviewId) => {
          try {
            const data = await fetchReviewCost(reviewId)
            return { reviewId, data, error: null as string | null }
          } catch (err: any) {
            console.error(`Error fetching costs for review ${reviewId}:`, err)
            return {
              reviewId,
              data: null,
              error: err?.message || 'Unable to load costs',
            }
          }
        }),
      )

      if (cancelled) {
        return
      }

      const nextCostsById: Record<string, SRCostSummary> = {}
      const nextLoadingById: Record<string, boolean> = {}
      const nextErrorById: Record<string, string> = {}

      for (const result of results) {
        nextLoadingById[result.reviewId] = false
        if (result.data) {
          nextCostsById[result.reviewId] = result.data
        }
        if (result.error) {
          nextErrorById[result.reviewId] = result.error
        }
      }

      setCostsById(nextCostsById)
      setLoadingById(nextLoadingById)
      setErrorById(nextErrorById)
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [normalizedIdsKey])

  return { costsById, loadingById, errorById }
}

export function useExtractionCitationCosts(
  srId: string | null | undefined,
  citationIds: number[],
): ExtractionCitationCostsState {
  const normalizedSrId = String(srId || '').trim()
  const normalizedCitationIds = useMemo(
    () => Array.from(new Set(citationIds.map((citationId) => Number(citationId)).filter(Number.isFinite))),
    [citationIds],
  )
  const normalizedCitationIdsKey = useMemo(() => normalizedCitationIds.join('|'), [normalizedCitationIds])

  const [costsByCitationId, setCostsByCitationId] = useState<Record<number, ExtractionCitationCostSummary>>({})
  const [loadingByCitationId, setLoadingByCitationId] = useState<Record<number, boolean>>({})
  const [errorByCitationId, setErrorByCitationId] = useState<Record<number, string>>({})

  useEffect(() => {
    if (!normalizedSrId || normalizedCitationIds.length === 0) {
      setCostsByCitationId({})
      setLoadingByCitationId({})
      setErrorByCitationId({})
      return
    }

    let cancelled = false

    setLoadingByCitationId(
      normalizedCitationIds.reduce<Record<number, boolean>>((acc, citationId) => {
        acc[citationId] = true
        return acc
      }, {}),
    )
    setErrorByCitationId({})

    const load = async () => {
      let results: Array<{ citationId: number; data: ExtractionCitationCostSummary | null; error: string | null }> = []

      try {
        const response = await fetchExtractionCitationCosts(normalizedSrId, normalizedCitationIds)
        const responseByCitationId = new Map<number, ExtractionCitationCostSummary>(
          (response.costs || []).map((item) => [Number(item.citation_id), item]),
        )

        results = normalizedCitationIds.map((citationId) => ({
          citationId,
          data: responseByCitationId.get(citationId) || {
            citation_id: citationId,
            currency: 'USD',
            total_cost_usd: 0,
            parameters: {},
          },
          error: null,
        }))
      } catch (err: any) {
        console.error('Error fetching extraction costs batch:', err)
        results = normalizedCitationIds.map((citationId) => ({
          citationId,
          data: null,
          error: err?.message || 'Unable to load extraction costs',
        }))
      }

      if (cancelled) {
        return
      }

      const nextCostsByCitationId: Record<number, ExtractionCitationCostSummary> = {}
      const nextLoadingByCitationId: Record<number, boolean> = {}
      const nextErrorByCitationId: Record<number, string> = {}

      for (const result of results) {
        nextLoadingByCitationId[result.citationId] = false
        if (result.data) {
          nextCostsByCitationId[result.citationId] = result.data
        }
        if (result.error) {
          nextErrorByCitationId[result.citationId] = result.error
        }
      }

      setCostsByCitationId(nextCostsByCitationId)
      setLoadingByCitationId(nextLoadingByCitationId)
      setErrorByCitationId(nextErrorByCitationId)
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [normalizedCitationIdsKey, normalizedSrId])

  return { costsByCitationId, loadingByCitationId, errorByCitationId }
}
