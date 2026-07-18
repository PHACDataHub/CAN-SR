import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CitationExportDialog } from './CitationExportDialog'
import { downloadCitationExport, loadCitationExportSchema } from '@/hooks/use-citation-export'

vi.mock('@/hooks/use-citation-export', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/hooks/use-citation-export')>()
  return {
    ...original,
    loadCitationExportSchema: vi.fn(),
    downloadCitationExport: vi.fn(),
  }
})

vi.mock('@/app/[lang]/DictionaryProvider', () => ({
  useDictionary: () => ({
    citationExport: {
      title: 'Export citations', description: 'Choose fields', loading: 'Loading',
      loadError: 'Could not load', retry: 'Retry', exportError: 'Could not export',
      rows: 'Rows', all: 'All', l1Included: 'L1 included', l2Included: 'L2 included',
      currentView: 'Current view', unavailable: 'Unavailable', noneAvailable: 'None',
      selectAll: 'Select all',
      selected: '{count} columns selected', cancel: 'Cancel', preparing: 'Preparing',
      exportCsv: 'Export CSV',
    },
  }),
}))

const schema = {
  schema_version: 1 as const,
  format: 'csv' as const,
  row_scopes: ['all', 'l1_included', 'l2_included', 'citation_ids'],
  groups: [
    {
      id: 'citation', label: 'Citation details', dimensions: [],
      items: [
        { id: 'citation.id', label: 'Citation ID', default_selected: true },
        { id: 'citation.title', label: 'Title', default_selected: true },
      ],
    },
    {
      id: 'l1', label: 'L1 screening',
      dimensions: [
        { id: 'human_answer', label: 'Human answers', default_selected: true },
        { id: 'ai_answer', label: 'AI answers', default_selected: false },
      ],
      items: [{
        id: 'l1.current', label: 'Current question?', default_selected: true,
        available_dimensions: ['human_answer'],
      }],
    },
  ],
}

describe('CitationExportDialog', () => {
  beforeEach(() => {
    vi.mocked(loadCitationExportSchema).mockResolvedValue(schema)
    vi.mocked(downloadCitationExport).mockResolvedValue(undefined)
  })

  it('loads defaults and submits current-view scope with exact selections', async () => {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    render(<CitationExportDialog srId="review/1" open onOpenChange={onOpenChange} currentViewIds={[7, 9]} />)

    expect(await screen.findByText('3 columns selected')).toBeInTheDocument()
    expect(loadCitationExportSchema).toHaveBeenCalledWith('review/1')
    await user.click(screen.getByRole('radio', { name: 'Current view' }))
    await user.click(screen.getByRole('button', { name: 'Export CSV' }))

    expect(downloadCitationExport).toHaveBeenCalledWith('review/1', {
      schema_version: 1,
      format: 'csv',
      row_scope: { kind: 'citation_ids', citation_ids: [7, 9] },
      selections: [
        { group: 'citation', items: ['citation.id', 'citation.title'], dimensions: [] },
        { group: 'l1', items: ['l1.current'], dimensions: ['human_answer'] },
      ],
    })
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('shows a schema error and retries successfully', async () => {
    const user = userEvent.setup()
    vi.mocked(loadCitationExportSchema)
      .mockRejectedValueOnce(new Error('Not Found'))
      .mockResolvedValueOnce(schema)

    render(<CitationExportDialog srId="review-1" open onOpenChange={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not Found')
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('3 columns selected')).toBeInTheDocument()
    expect(loadCitationExportSchema).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('radio', { name: /Current view/ })).toBeDisabled()
  })

  it('selects every option and becomes indeterminate when one child is cleared', async () => {
    const user = userEvent.setup()
    render(<CitationExportDialog srId="review-1" open onOpenChange={vi.fn()} />)

    const selectAll = await screen.findByRole('checkbox', { name: 'Select all' })
    await user.click(selectAll)

    expect(selectAll).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Select all Citation details' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Select all L1 screening' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'AI answers' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Current question?' })).toBeChecked()
    expect(screen.getByText('3 columns selected')).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Title' }))
    expect(selectAll).toHaveAttribute('data-state', 'indeterminate')
    expect(screen.getByRole('checkbox', { name: 'Select all Citation details' }))
      .toHaveAttribute('data-state', 'indeterminate')
    expect(screen.getByRole('checkbox', { name: 'Select all L1 screening' })).toBeChecked()
  })

  it('clears a question only when no selected dimension applies to it', async () => {
    const user = userEvent.setup()
    render(<CitationExportDialog srId="review-1" open onOpenChange={vi.fn()} />)

    await user.click(await screen.findByRole('checkbox', { name: 'Select all' }))
    const question = screen.getByRole('checkbox', { name: 'Current question?' })
    expect(question).toBeChecked()

    await user.click(screen.getByRole('checkbox', { name: 'AI answers' }))
    expect(question).toBeChecked()

    await user.click(screen.getByRole('checkbox', { name: 'Human answers' }))
    expect(question).not.toBeChecked()
    expect(question).toBeDisabled()
  })
})