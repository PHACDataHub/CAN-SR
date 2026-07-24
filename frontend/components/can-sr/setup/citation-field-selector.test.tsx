import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CitationFieldSelector from './citation-field-selector'
import { emptyCriteria } from './criteria-types'

const labels = new Proxy({}, { get: (_target, property) => String(property) }) as Record<string, string>

describe('CitationFieldSelector', () => {
  it('selects and reorders fields and shows DOI suggestions', async () => {
    const user = userEvent.setup()
    const dispatch = vi.fn()
    const criteria = emptyCriteria()
    criteria.citation_fields.l1_include = ['Title', 'Missing']
    render(<CitationFieldSelector state={{ criteria, revision: 1, dirty: false }} dispatch={dispatch} labels={labels} contract={{ fields: [
      { name: 'Title', data_type: 'text', doi_likelihood: 0 }, { name: 'DOI', data_type: 'text', doi_likelihood: 100 },
    ], doi_suggestions: ['DOI'], unavailable_configured_fields: ['Missing'] }} />)
    expect(screen.getByText(/Missing.*unavailableField/)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'DOI · likelyDoi' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'moveUp Missing' }))
    expect(dispatch).toHaveBeenCalledWith({ type: 'set-citation-fields', value: ['Missing', 'Title'] })
    await user.click(screen.getByRole('checkbox', { name: 'DOI' }))
    expect(dispatch).toHaveBeenLastCalledWith({ type: 'set-citation-fields', value: ['Title', 'Missing', 'DOI'] })
  })
})
