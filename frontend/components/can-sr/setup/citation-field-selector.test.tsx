import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CitationFieldSelector from './citation-field-selector'
import { emptyCriteria } from './criteria-types'

const labels = new Proxy(
  {},
  { get: (_target, property) => String(property) },
) as Record<string, string>

describe('CitationFieldSelector', () => {
  it('adds, removes, and reorders configured title/abstract fields', async () => {
    const user = userEvent.setup()
    const dispatch = vi.fn()
    const criteria = emptyCriteria()
    criteria.citation_fields.l1_include = ['Title', 'Missing']
    render(
      <CitationFieldSelector
        state={{ criteria, revision: 1, dirty: false }}
        dispatch={dispatch}
        labels={labels}
        contract={{
          fields: [
            { name: 'Title', data_type: 'text' },
            { name: 'Abstract', data_type: 'text' },
            { name: 'DOI', data_type: 'text' },
          ],
          unavailable_configured_fields: ['Missing'],
        }}
      />,
    )
    expect(
      screen.getByRole('heading', { name: 'citationFields' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Missing/ })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'moveUp Missing' }))
    expect(dispatch).toHaveBeenCalledWith({
      type: 'set-citation-fields',
      value: ['Missing', 'Title'],
    })
    await user.click(screen.getByRole('button', { name: 'addAdditionalField' }))
    expect(dispatch).toHaveBeenLastCalledWith({
      type: 'set-citation-fields',
      value: ['Title', 'Missing', 'DOI'],
    })
    await user.click(
      screen.getByRole('button', { name: 'removeField Missing' }),
    )
    expect(dispatch).toHaveBeenLastCalledWith({
      type: 'set-citation-fields',
      value: ['Title'],
    })
    expect(screen.getByLabelText('doiField')).toHaveDisplayValue('noDoiField')
    expect(screen.getByLabelText('doiField')).toContainHTML(
      '<option value="DOI">DOI</option>',
    )
    expect(screen.queryByText('likelyDoi')).not.toBeInTheDocument()

    await user.click(
      screen.getByRole('button', { name: 'collapse citationFields' }),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('doiField')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'addAdditionalField' }),
    ).not.toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: 'expand citationFields' }),
    )
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByLabelText('doiField')).toBeInTheDocument()
  })
})
