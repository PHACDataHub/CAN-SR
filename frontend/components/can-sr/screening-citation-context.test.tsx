import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  humanAnswerStatus,
  resolveDisplayedAnswer,
  resolveConfiguredValue,
  ScreeningCitationContext,
} from './screening-citation-context'

describe('screening citation context helpers', () => {
  it('returns undefined when the citation row is unavailable', () => {
    expect(resolveConfiguredValue(null, 'Title')).toBeUndefined()
    expect(resolveConfiguredValue(undefined, 'Abstract')).toBeUndefined()
  })

  it('reports a missing configured answer when the citation row is unavailable', () => {
    expect(
      humanAnswerStatus(null, 'Screening answer', ['Include', 'Exclude']),
    ).toBe('missing')
    expect(
      humanAnswerStatus(undefined, 'Screening answer', ['Include', 'Exclude']),
    ).toBe('missing')
  })

  it('prefers a human answer and otherwise displays the AI answer without copying it', () => {
    expect(resolveDisplayedAnswer({ selected: 'Include' }, { selected: 'Exclude' })).toBe('Include')
    expect(resolveDisplayedAnswer(null, { selected: 'Exclude' })).toBe('Exclude')
    expect(resolveDisplayedAnswer('', JSON.stringify({ selected: 'Include' }))).toBe('Include')
    expect(resolveDisplayedAnswer(null, null)).toBe('')
  })
})

describe('ScreeningCitationContext', () => {
  it('displays only configured additional citation fields', () => {
    render(
      <ScreeningCitationContext
        citation={{
          id: 10,
          Title: 'A retrospective study',
          Abstract: 'Study abstract',
          Journal: 'Open Journal',
          Publication: '2024',
        }}
        fields={{
          title: 'Title',
          abstract: 'Abstract',
          l1_include: ['Journal'],
        }}
      />,
    )
    expect(
      screen.getByRole('heading', { name: 'A retrospective study' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Study abstract')).toBeInTheDocument()
    expect(screen.getByText(/Journal:/)).toBeInTheDocument()
    expect(screen.getByText(/Open Journal/)).toBeInTheDocument()
    expect(screen.queryByText(/Publication:/)).not.toBeInTheDocument()
    expect(screen.queryByText(/2024/)).not.toBeInTheDocument()
  })
})
