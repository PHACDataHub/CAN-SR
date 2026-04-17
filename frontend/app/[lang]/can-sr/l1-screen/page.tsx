'use client'

import CitationsListPage from '@/components/can-sr/CitationListPage'

import type {
  AiCall,
  BuildCitationAiCalls,
} from '@/components/can-sr/CitationListPage'

const buildCitationAiCalls: BuildCitationAiCalls = ({
  srId,
  citationId,
  model,
  criteria,
  getAuthHeaders,
}) => {
  // Phase 2 wiring: L1 run-all uses the agentic orchestrator endpoint.
  // We keep the existing “Run all AI” modal behavior, but instead of running per-question
  // classify calls, we run a single orchestrated run per citation.
  return [
    {
      key: `l1_agentic_run`,
      label: `L1 agentic (screening + critical)`,
      run: async () => {
        const headers = {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        }

        const res = await fetch('/api/can-sr/screen/title-abstract/run', {
          method: 'POST',
          headers,
          body: JSON.stringify({
            sr_id: srId,
            citation_id: Number(citationId),
            model,
            temperature: 0.0,
            max_tokens: 1200,
            prompt_version: 'v1',
          }),
        })

        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `L1 agentic run failed (${res.status})`)
        }
      },
    },
  ]
}

export default function L1ScreenPage() {
  return (
    <CitationsListPage
      screeningStep="l1"
      pageview="l1-screen"
      buildCitationAiCalls={buildCitationAiCalls}
    />
  )
}
