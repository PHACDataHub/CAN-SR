'use client'

import CitationsListPage from '@/components/can-sr/CitationListPage'

import type {
  AiCall,
  BuildCitationAiCalls,
} from '@/components/can-sr/CitationListPage'

const buildCitationAiCalls: BuildCitationAiCalls = async ({
  srId,
  citationId,
  model,
  criteria,
  getAuthHeaders,
}) => {
  const headers = getAuthHeaders()

  // PDF gating: only proceed if citation has an uploaded PDF.
  // We only need fulltext_url for gating.
  try {
    const metaRes = await fetch(
      `/api/can-sr/citations/batch?sr_id=${encodeURIComponent(
        srId,
      )}&ids=${encodeURIComponent(String(citationId))}&fields=${encodeURIComponent(
        'id,fulltext_url',
      )}`,
      { method: 'GET', headers },
    )
    const meta = await metaRes.json().catch(() => ({}))
    const row = Array.isArray(meta?.citations) ? meta.citations[0] : null
    const ftUrl = row?.fulltext_url
    if (!ftUrl) return []
  } catch {
    // If gating fails, safest is to skip.
    return []
  }

  const calls: AiCall[] = []

  // Ensure fulltext extraction first (idempotent; backend short-circuits with MD5).
  calls.push({
    key: 'extract_fulltext',
    label: 'Extract full text',
    run: async () => {
      const res = await fetch(
        `/api/can-sr/citations/full-text?action=extract&sr_id=${encodeURIComponent(
          srId,
        )}&citation_id=${encodeURIComponent(String(citationId))}`,
        { method: 'POST', headers },
      )
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `Fulltext extraction failed (${res.status})`)
      }
    },
  })

  // Phase 2 wiring: run a single orchestrated fulltext screening+critical per citation.
  // (The backend reads SR criteria, so we do not need to fan out per-question calls.)
  calls.push({
    key: `l2_agentic_run`,
    label: `L2 agentic (screening + critical)`,
    run: async () => {
      const res = await fetch('/api/can-sr/screen/fulltext/run', {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sr_id: srId,
          citation_id: Number(citationId),
          model,
          temperature: 0.0,
          max_tokens: 2000,
          prompt_version: 'v1',
        }),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `L2 agentic run failed (${res.status})`)
      }
    },
  })

  return calls
}

export default function L2ScreenPage() {
  return (
    <CitationsListPage
      screeningStep="l2"
      pageview="l2-screen"
      buildCitationAiCalls={buildCitationAiCalls}
    />
  )
}
