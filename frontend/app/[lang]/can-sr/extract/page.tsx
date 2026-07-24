'use client'

import CitationsListPage from '@/components/can-sr/CitationListPage'
import { flattenExtractionParameters } from '@/components/can-sr/extraction-parameters'

import type {
  AiCall,
  BuildCitationAiCalls,
} from '@/components/can-sr/CitationListPage'

type ParametersParsed = {
  categories: string[]
  possible_parameters: any[][]
  descriptions: any[][]
  items?: any[]
}

const buildCitationAiCalls: BuildCitationAiCalls = async ({
  srId,
  citationId,
  model,
  getAuthHeaders,
  dict,
}) => {
  const headers = getAuthHeaders()

  // PDF gating: only proceed if citation has an uploaded PDF.
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
    return []
  }

  // Load parameter definitions (criteria_parsed.parameters) for this SR.
  // This is per-citation today (simple + correct); we can cache later if needed.
  let paramsFlat = [] as ReturnType<typeof flattenExtractionParameters>
  try {
    const res = await fetch(
      `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}&criteria_parsed=1`,
      { headers },
    )
    const data = await res.json().catch(() => ({}))
    const parsed = data?.criteria_parsed || data?.criteria || {}
    const paramsInfo: ParametersParsed | null =
      (parsed?.parameters as any) || null

    if (paramsInfo) {
      paramsFlat = flattenExtractionParameters(paramsInfo)
    }
  } catch (e) {
    console.warn('Failed to load parameters for extraction', e)
  }

  const calls: AiCall[] = []

  calls.push({
    key: 'extract_fulltext',
    label: dict?.extract?.extractingFullText || 'Extract full text',
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

  for (let i = 0; i < paramsFlat.length; i++) {
    const p = paramsFlat[i]
    calls.push({
      key: `extract_param_${i}`,
      label: `${dict?.extract?.suggesting || 'Extract'}: ${p.name}`,
      run: async () => {
        const res = await fetch(
          `/api/can-sr/extract?action=extract-parameter&sr_id=${encodeURIComponent(
            srId,
          )}&citation_id=${encodeURIComponent(String(citationId))}`,
          {
            method: 'POST',
            headers: { ...headers, 'Content-Type': 'application/json' },
            body: JSON.stringify({
              parameter_name: p.name,
              parameter_description: p.description,
              unit_instructions: p.unit_instructions,
              calculation: p.calculation,
              options: p.options,
              option_contexts: p.option_contexts,
              model,
              temperature: 0.0,
              max_tokens: 512,
            }),
          },
        )
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `Parameter extract failed (${res.status})`)
        }
      },
    })
  }

  return calls
}

export default function ExtractPage() {
  return (
    <CitationsListPage
      screeningStep="extract"
      pageview="extract"
      buildCitationAiCalls={buildCitationAiCalls}
    />
  )
}
