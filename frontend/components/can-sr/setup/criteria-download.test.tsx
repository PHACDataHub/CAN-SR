import { describe, expect, it } from 'vitest'
import { emptyCriteria } from './criteria-types'
import { serializeCriteriaDraft } from './criteria-download'

describe('serializeCriteriaDraft', () => {
  it('exports the complete canonical draft as YAML-compatible JSON', () => {
    const criteria = emptyCriteria()
    criteria.citation_fields.l1_include = ['Title', 'Abstract']
    const serialized = serializeCriteriaDraft(criteria)
    expect(JSON.parse(serialized)).toEqual(criteria)
    expect(serialized).toContain('"schema_version": 2')
  })
})
