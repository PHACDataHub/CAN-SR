import type { CriteriaConfig } from './criteria-types'

// JSON is a valid YAML 1.2 document and preserves the canonical object exactly.
export const serializeCriteriaDraft = (criteria: CriteriaConfig) => `${JSON.stringify(criteria, null, 2)}\n`

export function downloadCriteriaDraft(criteria: CriteriaConfig) {
  const url = URL.createObjectURL(new Blob([serializeCriteriaDraft(criteria)], { type: 'text/yaml;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'criteria-local-draft.yaml'
  anchor.click()
  URL.revokeObjectURL(url)
}
