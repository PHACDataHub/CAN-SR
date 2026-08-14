import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

import ReferencesWorkspace from './references-workspace'

const { authenticatedFetch, getCurrentUser } = vi.hoisted(() => ({
  authenticatedFetch: vi.fn(),
  getCurrentUser: vi.fn(),
}))

vi.mock('@/lib/auth', () => ({ authenticatedFetch, getCurrentUser }))

vi.mock('next/link', () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode
    href: string
  }) => <a href={href}>{children}</a>,
}))

const copy = {
  gridTitle: 'References workspace',
  empty: 'No references yet.',
  datasetReady: 'Dataset ready.',
  gridDeferred: 'Grid deferred.',
  search: 'Search references',
  loading: 'Loading references…',
  gridFailed: 'Unable to load references.',
  noMatches: 'No references match this search.',
  results: '{count} references',
  previous: 'Previous',
  next: 'Next',
  databaseSearch: 'Database Search',
  add: 'Add references',
  dialogTitle: 'Upload a reference file',
  dialogDescription: 'Import references immediately.',
  file: 'Reference file',
  import: 'Import references',
  imported: 'Imported: {count}',
  importFailed: 'Import failed',
  missingTitle: 'Missing Title column',
  missingAbstract: 'Missing Abstract column',
  additionalColumns: 'Additional columns preserved',
  cancel: 'Cancel',
  working: 'Working...',
  rows: 'Rows: {count}',
  mapping: 'Mapping',
  unmapped: 'unmapped',
  missing: 'Missing',
  excluded: 'Excluded',
  previewFailed: 'Preview failed',
  mappingFailed: 'Mapping failed',
  commitFailed: 'Commit failed',
  committed: 'Committed: {count}',
  reconciliation:
    'Reconciliation: {new} new; {existing} exact existing matches.',
  matchesDoNotOverwrite:
    'Exact matches do not overwrite citations or screening decisions.',
  ambiguousMatches:
    '{count} rows have ambiguous exact matches and must be resolved before import.',
  ambiguousRows: 'Ambiguous source rows: {rows}.',
  excludeAmbiguousRows: 'Exclude these ambiguous rows from this import.',
  ambiguousResolutionList: 'Ambiguous row resolution',
  excludeAmbiguousRow: 'Exclude source row {row} from this import.',
  ambiguousAcknowledgement:
    'Ambiguous rows acknowledged for exclusion: {acknowledged} of {total}.',
  excludedAmbiguousRows:
    '{count} ambiguous rows will be excluded from this import.',
  invalidReconciliationRows: '{count} rows are invalid and cannot be imported.',
  sortBy: 'Sort by {column}',
  columns: 'Columns',
  columnsTitle: 'Choose visible columns',
  columnsDescription: 'Choose fields.',
  saveColumns: 'Save columns',
  moveColumnUp: 'Move {column} up',
  moveColumnDown: 'Move {column} down',
}

beforeEach(() => {
  if (!File.prototype.text) {
    Object.defineProperty(File.prototype, 'text', {
      configurable: true,
      value() {
        return new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result || ''))
          reader.onerror = () => reject(reader.error)
          reader.readAsText(this)
        })
      },
    })
  }
  getCurrentUser.mockResolvedValue({ email: 'member@example.com' })
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [],
      total_count: 0,
      page: 1,
      page_size: 25,
      columns: ['id'],
    }),
  })
})

it('loads a server-paginated workspace grid for an existing dataset', async () => {
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [{ id: 1, title: 'A study', abstract: 'Summary' }],
      total_count: 1,
      page: 1,
      page_size: 25,
      columns: ['id', 'title', 'abstract'],
    }),
  })
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await waitFor(() => expect(screen.getByText('A study')).toBeInTheDocument())
  expect(authenticatedFetch).toHaveBeenCalledWith(
    expect.stringContaining(
      '/api/can-sr/citations/workspace?sr_id=review-1&page=1&page_size=25',
    ),
  )
})

it('requests server-side sorting when a workspace column header is selected', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [{ id: 1, title: 'A study', abstract: 'Summary' }],
      total_count: 1,
      page: 1,
      page_size: 25,
      columns: ['id', 'title', 'abstract'],
      sort: 'id',
      direction: 'asc',
      query_fingerprint: 'sha256:workspace',
    }),
  })
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await user.click(await screen.findByRole('button', { name: 'Sort by title' }))
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('sort=title&direction=asc'),
    ),
  )
})

it('saves selected workspace columns and reloads the grid with them', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(
    async (url: string, options?: RequestInit) => {
      if (url.includes('/workspace/preferences')) {
        if (options?.method === 'PUT')
          return { ok: true, json: async () => ({ columns: ['id', 'title'] }) }
        return { ok: true, json: async () => ({ columns: null }) }
      }
      return {
        ok: true,
        json: async () => ({
          citations: [{ id: 1, title: 'A study', abstract: 'Summary' }],
          total_count: 1,
          page: 1,
          page_size: 25,
          columns: ['id', 'title', 'abstract'],
          available_columns: ['id', 'title', 'abstract'],
          sort: 'id',
          direction: 'asc',
          query_fingerprint: 'sha256:workspace',
        }),
      }
    },
  )
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await user.click(await screen.findByRole('button', { name: 'Columns' }))
  await user.click(screen.getByRole('checkbox', { name: 'abstract' }))
  await user.click(screen.getByRole('button', { name: 'Save columns' }))
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/workspace/preferences?sr_id=review-1'),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ columns: ['id', 'title'] }),
      }),
    ),
  )
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('columns=id%2Ctitle'),
    ),
  )
})

it('warns about missing required columns without importing', async () => {
  const user = userEvent.setup()
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(screen.getByRole('button', { name: 'Add references' }))
  await user.upload(
    screen.getByLabelText('Reference file'),
    new File(['Title\nA'], 'invalid.csv', { type: 'text/csv' }),
  )
  await user.click(screen.getByRole('button', { name: 'Import references' }))
  expect(await screen.findByText('Missing Abstract column')).toBeInTheDocument()
  expect(authenticatedFetch).not.toHaveBeenCalledWith(
    expect.stringContaining('/citations/import?'),
    expect.anything(),
  )
})

it('reports an import API failure', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(async (url: string) => ({
    ok: !url.includes('/citations/import?'),
    json: async () =>
      url.includes('/citations/import?')
        ? { detail: 'Server rejected import' }
        : {
            citations: [],
            total_count: 0,
            page: 1,
            page_size: 25,
            columns: ['id'],
          },
  }))
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(screen.getByRole('button', { name: 'Add references' }))
  await user.upload(
    screen.getByLabelText('Reference file'),
    new File(['Title,Abstract\nA,B'], 'append.csv', { type: 'text/csv' }),
  )
  await user.click(screen.getByRole('button', { name: 'Import references' }))
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Server rejected import',
  )
})
