import { describe, expect, it } from 'vitest'
import { humanAnswerStatus, resolveConfiguredValue } from './screening-citation-context'

describe('screening citation context helpers', () => {
  it('returns undefined when the citation row is unavailable', () => {
    expect(resolveConfiguredValue(null, 'Title')).toBeUndefined()
    expect(resolveConfiguredValue(undefined, 'Abstract')).toBeUndefined()
  })

  it('reports a missing configured answer when the citation row is unavailable', () => {
    expect(humanAnswerStatus(null, 'Screening answer', ['Include', 'Exclude'])).toBe('missing')
    expect(humanAnswerStatus(undefined, 'Screening answer', ['Include', 'Exclude'])).toBe('missing')
  })
})
