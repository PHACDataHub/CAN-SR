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
  const calls: AiCall[] = []

  for (let i = 0; i < (criteria?.questions || []).length; i++) {
    const question = criteria.questions[i]
    const options = criteria.possible_answers?.[i] || []

    calls.push({
      key: `l1_classify_${i}`,
      label: `L1: ${question}`,
      run: async () => {
        const headers = {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        }

        const res = await fetch(
          `/api/can-sr/screen?action=classify&sr_id=${encodeURIComponent(
            srId,
          )}&citation_id=${encodeURIComponent(String(citationId))}`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({
              question,
              options,
              include_columns: ['title', 'abstract'],
              screening_step: 'l1',
              model,
              temperature: 0.0,
              max_tokens: 2000,
            }),
          },
        )

        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `L1 classify failed (${res.status})`)
        }
      },
    })
  }

  return calls
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
