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
  searchHint: 'Press Enter to search',
  loading: 'Loading references…',
  gridFailed: 'Unable to load references.',
  noMatches: 'No references match this search.',
  results: '{count} references',
  previous: 'Previous',
  next: 'Next',
  databaseSearch: 'Database Search',
  add: 'Add references',
  addReferencesTitle: 'Add References',
  dialogTitle: 'Add References',
  dialogDescription: 'Import references immediately.',
  file: 'Reference file',
  searchString: 'search string',
  beginSearch: 'Begin Search',
  import: 'Import references',
  imported: 'Imported: {count}',
  duplicatesSkipped: '{count} duplicates skipped.',
  duplicatesDetected:
    '{count} duplicate references detected. They will be merged unless Import Duplicates is selected.',
  includeDuplicates: 'Import Duplicates',
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
  filterBy: 'Filter by {column}',
  selectAll: 'Select all citations on this page',
  selectCitation: 'Select citation {id}',
  columns: 'Columns',
  columnsTitle: 'Choose Duplication Field',
  columnsDescription: 'Choose fields.',
  saveColumns: 'Save columns',
  moveColumnUp: 'Move {column} up',
  moveColumnDown: 'Move {column} down',
  deleting: 'Deleting…',
  deleteSelected: 'Delete {count} selected citations',
  duplicateGroupReview: 'Duplicate group review',
  groupSummary: 'Group {current} of {total} · {status} · {count} records',
  restore: 'Restore',
  minimize: 'Minimize',
  record: 'Record {id}',
  suggestedSurvivor: 'Suggested survivor',
  selectSurvivor: 'Select survivor',
  reviewDecision: 'Review decision:',
  confirmDuplicate: 'Confirm duplicate',
  keepBoth: 'Keep both',
  defer: 'Defer',
  deleteCitation: 'Delete {id}',
  survivor: 'Survivor',
  staleSurvivor:
    'The saved survivor is no longer in this group; a current member was selected.',
  chooseSelection: 'Choose citation selection',
  none: 'None',
  all: 'All',
  suggestedDuplicates: 'Suggested duplicates',
  filterDuplicateStatus: 'Filter duplicate status',
  showDuplicateStatusFilter: 'Show duplicate status filter',
  filterDuplicateStatuses: 'Filter duplicate statuses',
  duplicateStatus: 'Duplicate status',
  showReferencesMatching: 'Show references matching',
  allStatuses: 'All statuses',
  exactDuplicates: 'Exact duplicates',
  possibleDuplicates: 'Possible duplicates',
  noDuplicateMatch: 'No duplicate match',
  configureDuplicateFields: 'Configure duplicate matching fields',
  runningDuplicateCalculation: 'Running duplicate calculation',
  runDuplicateCalculation: 'Run duplicate calculation',
  rerunDuplicateCalculation: 'Rerun duplicate calculation',
  duplicateMatchingFields: 'Duplicate matching fields',
  duplicateFieldsDescription:
    'Visible fields are added automatically. Hidden fields remain configured.',
  deduplicationSettings: 'Deduplication Settings',
  selectDeduplicationFields: 'Select Deduplication Fields',
  selectAllDeduplicationColumns: 'Select All Columns',
  clearFilter: 'Clear',
  applyFilter: 'Apply',
  resizeColumn: 'Resize column',
  changeFile: 'Change file',
  chooseFile: 'Choose file',
  removeFile: 'Remove',
  searchDescription:
    'Search PubMed, Scopus, and Europe PMC using a database-specific search string.',
  selectedFile: 'Selected file:',
  exactDuplicateMatch: 'Exact duplicate match',
  possibleDuplicateMatch: 'Possible duplicate match',
  keptBothReviewGroup: 'Kept both; review duplicate group',
  openDuplicateReview: 'Open duplicate group review for citation {id}',
  reviewKeptBothGroup: 'Review kept-both group',
  openDuplicateGroupReview: 'Open duplicate group review',
  row: 'Row {number}',
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

it('keeps reference search compact beside add references and submits on Enter', async () => {
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
  const user = userEvent.setup()
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  const searchInput = await screen.findByRole('searchbox', {
    name: 'Search references',
  })
  expect(searchInput).toHaveClass('h-9')
  expect(searchInput.parentElement).toHaveClass('relative')
  expect(screen.queryByText('Press Enter to search')).not.toBeInTheDocument()
  expect(screen.queryByText('Enter')).not.toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: 'Add references' }),
  ).toBeInTheDocument()
  expect(searchInput.parentElement?.parentElement?.parentElement).toHaveClass(
    'items-end',
  )

  await waitFor(() => expect(authenticatedFetch).toHaveBeenCalled())
  authenticatedFetch.mockClear()
  await user.type(searchInput, 'diabetes')
  expect(authenticatedFetch).not.toHaveBeenCalled()
  expect(screen.getByText('Enter')).toBeInTheDocument()

  await user.keyboard('{Enter}')
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('search=diabetes'),
    ),
  )

  authenticatedFetch.mockClear()
  await user.clear(searchInput)
  expect(screen.queryByText('Enter')).not.toBeInTheDocument()
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/citations/workspace?'),
    ),
  )
  expect(
    authenticatedFetch.mock.calls.some(([url]) => !url.includes('search=')),
  ).toBe(true)
})

it('searches the selected database from the Add References modal', async () => {
  const user = userEvent.setup()
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await user.click(screen.getByRole('button', { name: 'Add references' }))
  expect(
    screen.getByRole('heading', { name: 'Add References' }),
  ).toBeInTheDocument()
  await user.click(screen.getByRole('tab', { name: 'Search databases' }))
  await user.click(screen.getByRole('radio', { name: /Pubmed/i }))
  await user.type(
    screen.getByRole('textbox', { name: /Pubmed search string/i }),
    'cancer',
  )
  await user.click(screen.getByRole('button', { name: 'Begin Search' }))

  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      '/api/can-sr/search?sr_id=review-1',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ database: 'Pubmed', search_term: 'cancer' }),
      }),
    ),
  )
})

it('shows Add references on a fresh workspace', async () => {
  const user = userEvent.setup()
  render(<ReferencesWorkspace srId="review-1" hasDataset={false} copy={copy} />)

  await user.click(screen.getByRole('button', { name: 'Add references' }))

  expect(
    screen.getByRole('heading', { name: 'Add References' }),
  ).toBeInTheDocument()
})

it('renders fifteen empty rows when the workspace has no references', async () => {
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await waitFor(() => {
    const rows = screen.getAllByRole('row', { name: /^Row / })
    expect(rows).toHaveLength(15)
    expect(
      rows.every((row) => row.querySelector('td')?.textContent === ''),
    ).toBe(true)
    expect(
      rows.every((row) =>
        Array.from(row.querySelectorAll('td')).every(
          (cell) =>
            cell.className.includes('py-2') &&
            cell
              .querySelector('[aria-hidden="true"]')
              ?.className.includes('h-5'),
        ),
      ),
    ).toBe(true)
  })
})

it('loads the complete workspace grid for an existing dataset', async () => {
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [{ id: 1, title: 'A study', abstract: 'Summary' }],
      total_count: 1,
      columns: ['id', 'title', 'abstract'],
    }),
  })
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await waitFor(() => expect(screen.getByText('A study')).toBeInTheDocument())
  expect(authenticatedFetch).toHaveBeenCalledWith(
    expect.stringContaining(
      '/api/can-sr/citations/workspace?sr_id=review-1&sort=id&direction=asc',
    ),
  )
  expect(screen.getAllByText('1', { selector: 'td' })).toHaveLength(2)
  expect(screen.getByLabelText('Row 2')).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Previous' }),
  ).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
})

it('clears all selected citations with the None selection option', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [
        { id: 1, title: 'First study' },
        { id: 2, title: 'Second study' },
      ],
      total_count: 2,
      columns: ['id', 'title'],
    }),
  })

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await waitFor(() =>
    expect(screen.getByText('First study')).toBeInTheDocument(),
  )

  await user.click(
    screen.getByRole('checkbox', {
      name: 'Select all citations on this page',
    }),
  )
  expect(
    screen.queryByRole('button', { name: 'Choose citation selection' }),
  ).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'All' }))
  expect(
    screen.getByLabelText('Select all citations on this page'),
  ).toHaveAttribute('data-state', 'checked')

  await user.click(
    screen.getByRole('checkbox', {
      name: 'Select all citations on this page',
    }),
  )
  await user.click(screen.getByRole('button', { name: 'None' }))
  expect(
    screen.getByLabelText('Select all citations on this page'),
  ).toHaveAttribute('data-state', 'unchecked')
})

it('opens duplicate status selection in a popup and applies the chosen filter', async () => {
  const user = userEvent.setup()
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await user.click(
    await screen.findByRole('button', { name: 'Show duplicate status filter' }),
  )
  expect(
    screen.getByRole('combobox', { name: 'Show references matching' }),
  ).toHaveValue('')
  expect(
    authenticatedFetch.mock.calls.some(([url]) =>
      url.includes('duplicate_status='),
    ),
  ).toBe(false)

  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Show references matching' }),
    'exact',
  )
  expect(
    authenticatedFetch.mock.calls.some(([url]) =>
      url.includes('duplicate_status='),
    ),
  ).toBe(false)

  await user.click(screen.getByRole('button', { name: 'Apply' }))
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('duplicate_status=exact'),
    ),
  )
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
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

it('keeps the current grid visible while sorting is loading', async () => {
  const user = userEvent.setup()
  let resolveSort: ((response: unknown) => void) | undefined
  const workspaceResponse = {
    ok: true,
    json: async () => ({
      citations: [{ id: 1, title: 'A study', abstract: 'Summary' }],
      total_count: 1,
      columns: ['id', 'title', 'abstract'],
    }),
  }
  authenticatedFetch.mockImplementation((url: string) => {
    if (url.includes('/citations/workspace?') && url.includes('sort=title')) {
      return new Promise((resolve) => {
        resolveSort = resolve
      })
    }
    return workspaceResponse
  })

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await screen.findByText('A study')
  await user.click(await screen.findByRole('button', { name: 'Sort by title' }))

  expect(screen.getByText('A study')).toBeInTheDocument()
  expect(screen.queryByText(copy.loading)).not.toBeInTheDocument()

  resolveSort?.({
    ok: true,
    json: async () => ({
      citations: [{ id: 1, title: 'A study', abstract: 'Summary' }],
      total_count: 1,
      columns: ['id', 'title', 'abstract'],
    }),
  })
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

it('shares selected imported columns with visible columns and duplicate matching', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(
    async (url: string, options?: RequestInit) => {
      if (url.includes('/citations/import?')) {
        return {
          ok: true,
          json: async () => ({ rows_inserted: 1, duplicates_skipped: 0 }),
        }
      }
      if (url.includes('/workspace/preferences')) {
        return {
          ok: true,
          json: async () => ({ columns: ['id', 'Title', 'Abstract'] }),
        }
      }
      if (url.includes('/deduplication-preferences')) {
        return {
          ok: true,
          json: async () => ({ fields: ['Title', 'Abstract'], threshold: 0.7 }),
        }
      }
      return {
        ok: true,
        json: async () => ({
          citations: [],
          total_count: 0,
          columns: ['id'],
          available_columns: ['id', 'Title', 'Abstract', 'Author'],
        }),
      }
    },
  )

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(screen.getByRole('button', { name: 'Add references' }))
  await user.upload(
    screen.getByLabelText('Reference file'),
    new File(
      ['Title,Abstract,Author\nA study,Summary,An author'],
      'references.csv',
      { type: 'text/csv' },
    ),
  )

  expect(await screen.findByRole('checkbox', { name: 'Title' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Abstract' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Author' })).toBeChecked()
  await user.selectOptions(screen.getByRole('combobox', { name: 'Title source field' }), 'Title')
  await user.selectOptions(screen.getByRole('combobox', { name: 'Abstract source field' }), 'Abstract')
  await user.click(screen.getByRole('checkbox', { name: 'Author' }))
  await user.click(screen.getByRole('button', { name: 'Import references' }))

  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/workspace/preferences?sr_id=review-1'),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ columns: ['id', 'Title', 'Abstract'] }),
      }),
    ),
  )
  expect(authenticatedFetch).toHaveBeenCalledWith(
    expect.stringContaining('/deduplication-preferences?sr_id=review-1'),
    expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ fields: ['Title', 'Abstract'], threshold: 0.7 }),
    }),
  )
})

it('toggles all imported deduplication columns on and off', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [],
      total_count: 0,
      columns: ['id'],
    }),
  })

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(screen.getByRole('button', { name: 'Add references' }))
  await user.upload(
    screen.getByLabelText('Reference file'),
    new File(['Title,Abstract,Author\nA,B,C'], 'references.csv', {
      type: 'text/csv',
    }),
  )

  const selectAll = await screen.findByRole('checkbox', {
    name: 'Select All Columns',
  })
  expect(selectAll).toBeChecked()
  await user.click(selectAll)
  expect(selectAll).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Title' })).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Abstract' })).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Author' })).not.toBeChecked()

  await user.click(selectAll)
  expect(selectAll).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Title' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Abstract' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Author' })).toBeChecked()
})

it('loads and persists the selected duplicate matching threshold', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(
    async (url: string, options?: RequestInit) => {
      if (url.includes('/deduplication-preferences')) {
        if (options?.method === 'PUT')
          return {
            ok: true,
            json: async () => ({ fields: ['title'], threshold: 0.8 }),
          }
        return {
          ok: true,
          json: async () => ({ fields: ['title'], threshold: 0.8 }),
        }
      }
      return {
        ok: true,
        json: async () => ({
          citations: [{ id: 1, title: 'A study' }],
          total_count: 1,
          columns: ['id', 'title'],
          available_columns: ['id', 'title', 'abstract'],
        }),
      }
    },
  )

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(
    await screen.findByRole('button', {
      name: 'Configure duplicate matching fields',
    }),
  )
  expect(
    screen.getByRole('radiogroup', { name: 'Matching Strength' }),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('heading', { name: 'Deduplication Settings' }),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('heading', { name: 'Select Deduplication Fields' }),
  ).toBeInTheDocument()
  await user.click(
    screen.getByRole('button', {
      name: 'Configure duplicate matching fields',
    }),
  )
  expect(screen.queryByText('Deduplication Settings')).not.toBeInTheDocument()
  await user.click(
    screen.getByRole('button', {
      name: 'Configure duplicate matching fields',
    }),
  )
  expect(screen.getByRole('radio', { name: 'Strict' })).toHaveAttribute(
    'aria-checked',
    'true',
  )
  await user.click(screen.getByRole('radio', { name: 'Permissive' }))

  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/deduplication-preferences?sr_id=review-1'),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ fields: ['title'], threshold: 0.5 }),
      }),
    ),
  )
})

it('shows the refresh icon for fresh duplicate results and amber play for stale results', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(
    async (url: string, options?: RequestInit) => {
      if (
        url.includes('/deduplication-preferences') &&
        options?.method === 'PUT'
      )
        return { ok: true, json: async () => ({}) }
      return {
        ok: true,
        json: async () => ({
          citations: [{ id: 1, title: 'A study' }],
          total_count: 1,
          columns: ['id', 'title'],
          available_columns: ['id', 'title', 'abstract'],
          duplicate_run: { status: 'succeeded' },
        }),
      }
    },
  )

  const { container } = render(
    <ReferencesWorkspace srId="review-1" hasDataset copy={copy} />,
  )
  const rerunButton = await screen.findByRole('button', {
    name: 'Rerun duplicate calculation',
  })
  expect(rerunButton.querySelector('.lucide-refresh-cw')).toBeInTheDocument()

  await user.click(
    await screen.findByRole('button', {
      name: 'Configure duplicate matching fields',
    }),
  )
  await user.click(screen.getByRole('checkbox', { name: 'abstract' }))
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Rerun duplicate calculation' }),
    ).toHaveClass('text-amber-600'),
  )
  expect(container.querySelector('.lucide-play')).toBeInTheDocument()
})

it('dismisses duplicate matching fields when clicking outside its popover', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [{ id: 1, title: 'A study' }],
      total_count: 1,
      columns: ['id', 'title'],
      available_columns: ['id', 'title'],
    }),
  })
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await user.click(
    await screen.findByRole('button', {
      name: 'Configure duplicate matching fields',
    }),
  )
  expect(screen.getByText('Deduplication Settings')).toBeInTheDocument()
  await user.click(document.body)
  expect(screen.queryByText('Deduplication Settings')).not.toBeInTheDocument()
})

it('does not render a filter control for the ID column', async () => {
  authenticatedFetch.mockResolvedValue({
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
  })
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await screen.findByText('A study')
  expect(
    screen.queryByRole('button', { name: 'Filter by id' }),
  ).not.toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: 'Filter by title' }),
  ).toBeInTheDocument()
})

it('closes a column filter when its icon is clicked again', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockResolvedValue({
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
  })
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await screen.findByText('A study')
  const filterButton = screen.getByRole('button', { name: 'Filter by title' })
  await user.click(filterButton)
  expect(
    screen.getByRole('textbox', { name: 'Filter by title' }),
  ).toBeInTheDocument()

  await user.click(filterButton)
  expect(
    screen.queryByRole('textbox', { name: 'Filter by title' }),
  ).not.toBeInTheDocument()
})

it('allows selecting either duplicate survivor, minimizing review, and shows an X marker', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(
    async (url: string, options?: RequestInit) => {
      if (url.includes('/workspace/duplicate-reviews')) {
        if (options?.method === 'PUT') {
          return {
            ok: true,
            json: async () => ({
              group_id: 'duplicate-group-1',
              decision: 'confirmed_duplicate',
              survivor_id: 2,
            }),
          }
        }
        return { ok: true, json: async () => ({ reviews: [] }) }
      }
      if (url.includes('/workspace/preferences'))
        return { ok: true, json: async () => ({ columns: null }) }
      if (url.includes('/deduplication-preferences'))
        return { ok: true, json: async () => ({ fields: ['title'] }) }
      return {
        ok: true,
        json: async () => ({
          citations: [
            {
              id: 1,
              title: 'Same study',
              duplicate_status: 'exact',
              duplicate_group_id: 'duplicate-group-1',
            },
            {
              id: 2,
              title: 'Same study',
              duplicate_status: 'exact',
              duplicate_group_id: 'duplicate-group-1',
            },
            {
              id: 3,
              title: 'Another study',
              duplicate_status: 'exact',
              duplicate_group_id: 'duplicate-group-2',
            },
            {
              id: 4,
              title: 'Another study',
              duplicate_status: 'exact',
              duplicate_group_id: 'duplicate-group-2',
            },
          ],
          total_count: 2,
          columns: ['id', 'title'],
          available_columns: ['id', 'title'],
          duplicate_fields: ['title'],
          duplicate_groups: [
            {
              group_id: 'duplicate-group-1',
              citation_ids: [1, 2],
              status: 'exact',
              suggested_survivor_id: 1,
              members: [
                { id: 1, title: 'Same study' },
                { id: 2, title: 'Same study' },
              ],
            },
            {
              group_id: 'duplicate-group-2',
              citation_ids: [3, 4],
              status: 'exact',
              suggested_survivor_id: 3,
              members: [
                { id: 3, title: 'Another study' },
                { id: 4, title: 'Another study' },
              ],
            },
          ],
        }),
      }
    },
  )

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await screen.findByRole('heading', { name: 'Duplicate group review' })
  await user.click(
    screen.getByRole('checkbox', {
      name: 'Select all citations on this page',
    }),
  )
  await user.click(screen.getByRole('button', { name: 'Suggested duplicates' }))
  expect(
    screen.getByRole('checkbox', { name: 'Select citation 1' }),
  ).not.toBeChecked()
  expect(
    screen.getByRole('checkbox', { name: 'Select citation 2' }),
  ).toBeChecked()
  expect(
    screen.getByRole('checkbox', { name: 'Select citation 3' }),
  ).not.toBeChecked()
  expect(
    screen.getByRole('checkbox', { name: 'Select citation 4' }),
  ).toBeChecked()
  expect(
    screen.getAllByRole('button', {
      name: /Open duplicate group review for citation/,
    }),
  ).toHaveLength(4)
  await user.click(
    screen.getByRole('button', {
      name: 'Open duplicate group review for citation 3',
    }),
  )
  expect(screen.getByText(/Group 2 of 2/)).toBeInTheDocument()
  await user.click(
    screen.getByRole('button', {
      name: 'Open duplicate group review for citation 1',
    }),
  )
  expect(screen.getByText(/Group 1 of 2/)).toBeInTheDocument()
  await user.click(screen.getByRole('radio', { name: 'Select survivor' }))
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/workspace/duplicate-reviews?sr_id=review-1'),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          group_id: 'duplicate-group-1',
          decision: 'confirmed_duplicate',
          survivor_id: 2,
        }),
      }),
    ),
  )
  expect(
    screen.getByRole('button', { name: 'Minimize Duplicate group review' }),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Delete 1' })).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Confirm duplicate' }),
  ).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Delete 1' }))
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/workspace?sr_id=review-1'),
      expect.objectContaining({
        method: 'DELETE',
        body: expect.not.stringContaining('"group_ids"'),
      }),
    ),
  )
  const deletionRequest = authenticatedFetch.mock.calls.find(
    ([url, options]) =>
      url.includes('/workspace?sr_id=review-1') &&
      (options as RequestInit | undefined)?.method === 'DELETE',
  )
  expect(deletionRequest?.[1]).toEqual(
    expect.objectContaining({
      body: expect.stringContaining('"citation_ids":[1]'),
    }),
  )
  expect(screen.getByText(/Group 2 of 2/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Previous' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Previous group' }),
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Next group' }),
  ).not.toBeInTheDocument()

  await user.click(
    screen.getByRole('button', { name: 'Minimize Duplicate group review' }),
  )
  expect(screen.queryByText('Select survivor')).not.toBeInTheDocument()
  await user.click(
    screen.getByRole('button', { name: 'Restore Duplicate group review' }),
  )
  expect(screen.getByText('Select survivor')).toBeInTheDocument()
})

it('ignores a stale saved survivor and keeps one current member selected', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(async (url: string) => {
    if (url.includes('/workspace/duplicate-reviews')) {
      return {
        ok: true,
        json: async () => ({
          reviews: [
            {
              group_id: 'duplicate-group-stale',
              decision: 'confirmed_duplicate',
              survivor_id: 206,
            },
          ],
        }),
      }
    }
    if (url.includes('/workspace/preferences'))
      return { ok: true, json: async () => ({ columns: null }) }
    if (url.includes('/deduplication-preferences'))
      return { ok: true, json: async () => ({ fields: ['title'] }) }
    return {
      ok: true,
      json: async () => ({
        citations: [
          { id: 201, title: 'Same study', duplicate_status: 'exact' },
          { id: 300, title: 'Same study', duplicate_status: 'exact' },
        ],
        total_count: 2,
        columns: ['id', 'title'],
        available_columns: ['id', 'title'],
        duplicate_fields: ['title'],
        duplicate_groups: [
          {
            group_id: 'duplicate-group-stale',
            citation_ids: [201, 300],
            status: 'exact',
            suggested_survivor_id: 300,
            review: {
              group_id: 'duplicate-group-stale',
              decision: 'confirmed_duplicate',
              survivor_id: null,
              stale: true,
            },
            members: [
              { id: 201, title: 'Same study' },
              { id: 300, title: 'Same study' },
            ],
          },
        ],
      }),
    }
  })

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await screen.findByRole('heading', { name: 'Duplicate group review' })
  await user.click(
    screen.getByRole('button', {
      name: 'Restore Duplicate group review',
    }),
  )
  expect(
    screen.getByRole('radio', { name: 'Suggested survivor' }),
  ).toBeChecked()
  expect(
    screen.getByRole('radio', { name: 'Select survivor' }),
  ).not.toBeChecked()
  expect(screen.getByText(copy.staleSurvivor)).toBeInTheDocument()
})

it('shows a green marker for kept-both citations and opens their review group', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(async (url: string) => {
    if (url.includes('/workspace/duplicate-reviews')) {
      return {
        ok: true,
        json: async () => ({
          reviews: [
            { group_id: 'duplicate-group-kept', decision: 'not_duplicate' },
          ],
        }),
      }
    }
    if (url.includes('/workspace/preferences'))
      return { ok: true, json: async () => ({ columns: null }) }
    if (url.includes('/deduplication-preferences'))
      return { ok: true, json: async () => ({ fields: ['title'] }) }
    return {
      ok: true,
      json: async () => ({
        citations: [
          {
            id: 10,
            title: 'Kept study',
            duplicate_status: 'no_match',
            duplicate_group_id: 'duplicate-group-kept',
          },
          {
            id: 11,
            title: 'Kept study',
            duplicate_status: 'no_match',
            duplicate_group_id: 'duplicate-group-kept',
          },
        ],
        total_count: 2,
        columns: ['id', 'title'],
        duplicate_groups: [
          {
            group_id: 'duplicate-group-kept',
            citation_ids: [10, 11],
            status: 'exact',
            members: [
              { id: 10, title: 'Kept study' },
              { id: 11, title: 'Kept study' },
            ],
          },
        ],
      }),
    }
  })

  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await screen.findByRole('heading', { name: 'Duplicate group review' })
  expect(
    screen.getAllByRole('button', {
      name: /Open duplicate group review for citation/,
    }),
  ).toHaveLength(2)
  await user.click(
    screen.getByRole('button', {
      name: 'Open duplicate group review for citation 10',
    }),
  )
  expect(screen.getByText(/Group 1 of 1/)).toBeInTheDocument()
})

it('binds workspace column boundaries to explicit resizable widths', async () => {
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

  await screen.findByText('A study')
  const table = screen.getByRole('table')
  expect(table.querySelectorAll('col')[3]).toHaveStyle({ width: '160px' })
  expect(table.querySelectorAll('col')).toHaveLength(8)
  expect(
    screen.getByRole('button', { name: 'Resize column title' }),
  ).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Columns' })).toHaveLength(1)
  expect(screen.queryByText('Choose Duplication Field')).not.toBeInTheDocument()
})

it('opens the column chooser from the trailing plus column', async () => {
  authenticatedFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      citations: [{ id: 1, title: 'A study', abstract: 'Summary' }],
      total_count: 1,
      page: 1,
      page_size: 25,
      columns: ['id', 'title', 'abstract'],
      available_columns: ['id', 'title', 'abstract', 'author'],
      sort: 'id',
      direction: 'asc',
      query_fingerprint: 'sha256:workspace',
    }),
  })
  const user = userEvent.setup()
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)

  await screen.findByText('A study')
  await user.click(screen.getByRole('button', { name: 'Columns' }))

  const panel = screen.getByRole('dialog')
  expect(panel).toBeInTheDocument()
  expect(panel).toHaveClass(
    'absolute',
    'top-full',
    'right-0',
    'overflow-y-auto',
  )
  expect(panel).toHaveClass('w-[min(28rem,calc(100vw-2rem))]')
  expect(screen.queryByTestId('dialog-overlay')).not.toBeInTheDocument()
  expect(screen.getByText('Choose Duplication Field')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Columns' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('requires explicit title and abstract selections without importing', async () => {
  const user = userEvent.setup()
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(screen.getByRole('button', { name: 'Add references' }))
  await user.upload(
    screen.getByLabelText('Reference file'),
    new File(['Title\nA'], 'invalid.csv', { type: 'text/csv' }),
  )
  await user.click(screen.getByRole('button', { name: 'Import references' }))
  expect(
    await screen.findByText(
      'Select the source columns to use for Title and Abstract before importing.',
    ),
  ).toBeInTheDocument()
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
  await user.selectOptions(screen.getByRole('combobox', { name: 'Title source field' }), 'Title')
  await user.selectOptions(screen.getByRole('combobox', { name: 'Abstract source field' }), 'Abstract')
  await user.click(screen.getByRole('button', { name: 'Import references' }))
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Server rejected import',
  )
})

it('allows duplicate imports to be explicitly overridden', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(
    async (url: string, options?: RequestInit) => {
      if (url.includes('/duplicates/check?')) {
        return { ok: true, json: async () => ({ duplicates_count: 1 }) }
      }
      if (url.includes('/citations/import?')) {
        expect((options?.body as FormData).get('include_duplicates')).toBe(
          'true',
        )
        return {
          ok: true,
          json: async () => ({ rows_inserted: 2, duplicates_skipped: 0 }),
        }
      }
      return {
        ok: true,
        json: async () => ({ citations: [], total_count: 0, columns: ['id'] }),
      }
    },
  )
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(screen.getByRole('button', { name: 'Add references' }))
  await user.upload(
    screen.getByLabelText('Reference file'),
    new File(['Title,Abstract\nA,B'], 'duplicates.csv', { type: 'text/csv' }),
  )
  expect(
    await screen.findByText(
      '1 duplicate references detected. They will be merged unless Import Duplicates is selected.',
    ),
  ).toBeInTheDocument()
  await user.click(screen.getByRole('checkbox', { name: 'Import Duplicates' }))
  await user.selectOptions(screen.getByRole('combobox', { name: 'Title source field' }), 'Title')
  await user.selectOptions(screen.getByRole('combobox', { name: 'Abstract source field' }), 'Abstract')
  await user.click(screen.getByRole('button', { name: 'Import references' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Imported: 2')
})

it('does not display the duplicate import override when none are detected', async () => {
  const user = userEvent.setup()
  authenticatedFetch.mockImplementation(async (url: string) => {
    if (url.includes('/duplicates/check?')) {
      return { ok: true, json: async () => ({ duplicates_count: 0 }) }
    }
    return {
      ok: true,
      json: async () => ({ citations: [], total_count: 0, columns: ['id'] }),
    }
  })
  render(<ReferencesWorkspace srId="review-1" hasDataset copy={copy} />)
  await user.click(screen.getByRole('button', { name: 'Add references' }))
  await user.upload(
    screen.getByLabelText('Reference file'),
    new File(['Title,Abstract\nA,B'], 'new.csv', { type: 'text/csv' }),
  )
  await waitFor(() =>
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('/duplicates/check?'),
      expect.anything(),
    ),
  )
  expect(
    screen.queryByRole('checkbox', { name: 'Import Duplicates' }),
  ).not.toBeInTheDocument()
})
