'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Plus } from 'lucide-react'
import { authenticatedFetch } from '@/lib/auth'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'

type Props = {
  srId: string
  hasDataset: boolean | null
  copy: Record<string, string>
}

type Citation = Record<string, unknown>

type WorkspacePage = {
  citations: Citation[]
  total_count: number
  page: number
  page_size: number
  columns: string[]
  available_columns?: string[]
  sort: string
  direction: 'asc' | 'desc'
  query_fingerprint: string
}

export default function ReferencesWorkspace({ srId, hasDataset, copy }: Props) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [workspace, setWorkspace] = useState<WorkspacePage | null>(null)
  const [workspaceError, setWorkspaceError] = useState('')
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [deleting, setDeleting] = useState(false)
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState('id')
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc')
  const [visibleColumns, setVisibleColumns] = useState<string[] | null>(null)
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [draftColumns, setDraftColumns] = useState<string[]>([])
  const [columnsSaving, setColumnsSaving] = useState(false)
  const [datasetReady, setDatasetReady] = useState(Boolean(hasDataset))

  useEffect(() => {
    setDatasetReady(Boolean(hasDataset))
  }, [hasDataset])

  const loadWorkspace = async () => {
    if (!datasetReady) {
      setWorkspace(null)
      return
    }
    setWorkspaceLoading(true)
    setWorkspaceError('')
    const params = new URLSearchParams({
      sr_id: srId,
      page: String(page),
      page_size: '25',
      sort,
      direction,
    })
    if (search.trim()) params.set('search', search.trim())
    const activeFilters = Object.fromEntries(
      Object.entries(filters).filter(([, value]) => value.trim()),
    )
    if (Object.keys(activeFilters).length)
      params.set('filters', JSON.stringify(activeFilters))
    if (visibleColumns?.length) params.set('columns', visibleColumns.join(','))
    const response = await authenticatedFetch(
      `/api/can-sr/citations/workspace?${params}`,
    )
    const data = await response.json().catch(() => ({}))
    setWorkspaceLoading(false)
    if (!response.ok) {
      setWorkspaceError(data?.error || data?.detail || copy.gridFailed)
      return
    }
    setWorkspace(data)
  }

  useEffect(() => {
    void loadWorkspace()
    // loadWorkspace intentionally tracks the request inputs rather than its identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    srId,
    datasetReady,
    page,
    search,
    filters,
    sort,
    direction,
    visibleColumns,
  ])

  useEffect(() => {
    if (!datasetReady) return
    void (async () => {
      const response = await authenticatedFetch(
        `/api/can-sr/citations/workspace/preferences?sr_id=${encodeURIComponent(srId)}`,
      )
      const data = await response.json().catch(() => ({}))
      if (response.ok && Array.isArray(data?.columns) && data.columns.length) {
        setVisibleColumns(data.columns)
      }
    })()
  }, [srId, datasetReady])

  const close = () => {
    setOpen(false)
    setFile(null)
    setWarnings([])
    setMessage('')
  }

  const importFile = async () => {
    if (!file) return
    setBusy(true)
    setMessage('')
    const form = new FormData()
    form.append('file', file)
    form.append('commit_key', crypto.randomUUID())
    const text = await file.text()
    const headerLine = text.split(/\r?\n/, 1)[0] || ''
    const headers = file.name.toLowerCase().endsWith('.csv')
      ? headerLine
          .split(',')
          .map((value) => value.trim().replace(/^"|"$/g, ''))
          .filter(Boolean)
      : []
    const normalized = headers.map((value) =>
      value.toLowerCase().replace(/[^a-z0-9]+/g, ''),
    )
    const localWarnings: string[] = []
    if (!normalized.includes('title'))
      localWarnings.push(
        copy.missingTitle || 'The file is missing a Title column.',
      )
    if (!normalized.includes('abstract'))
      localWarnings.push(
        copy.missingAbstract || 'The file is missing an Abstract column.',
      )
    const extras = headers.filter(
      (_, index) => !['title', 'abstract'].includes(normalized[index]),
    )
    if (extras.length) {
      localWarnings.push(
        `${copy.additionalColumns || 'Additional source columns will be preserved as text'}: ${extras.join(', ')}`,
      )
    }
    setWarnings(localWarnings)
    if (!normalized.includes('title') || !normalized.includes('abstract')) {
      setBusy(false)
      return
    }
    const response = await authenticatedFetch(
      `/api/can-sr/citations/import?sr_id=${encodeURIComponent(srId)}`,
      { method: 'POST', body: form },
    )
    const data = await response.json().catch(() => ({}))
    setBusy(false)
    if (!response.ok) {
      setMessage(
        data?.error ||
          data?.detail ||
          copy.importFailed ||
          'Unable to import the references.',
      )
      return
    }
    setMessage(
      (copy.imported || 'Import complete: {count} citations added.').replace(
        '{count}',
        String(data.rows_inserted),
      ),
    )
    setDatasetReady(true)
    await loadWorkspace()
    setFile(null)
  }

  const toggleSort = (column: string) => {
    setPage(1)
    if (sort === column) {
      setDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(column)
      setDirection('asc')
    }
  }
  const toggleSelected = (id: number) => {
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id],
    )
  }
  const deleteSelected = async () => {
    if (!selectedIds.length) return
    setDeleting(true)
    const response = await authenticatedFetch(
      `/api/can-sr/citations/workspace?sr_id=${encodeURIComponent(srId)}`,
      {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ citation_ids: selectedIds }),
      },
    )
    const data = await response.json().catch(() => ({}))
    setDeleting(false)
    if (!response.ok) {
      setWorkspaceError(data?.error || data?.detail || copy.deleteFailed)
      return
    }
    setSelectedIds([])
    await loadWorkspace()
  }
  const openColumns = () => {
    setDraftColumns(workspace?.columns || visibleColumns || ['id'])
    setColumnsOpen(true)
  }
  const toggleColumn = (column: string) => {
    if (column === 'id') return
    setDraftColumns((current) =>
      current.includes(column)
        ? current.filter((value) => value !== column)
        : [...current, column],
    )
  }
  const moveColumn = (column: string, offset: -1 | 1) => {
    setDraftColumns((current) => {
      const index = current.indexOf(column)
      const nextIndex = index + offset
      if (index < 0 || nextIndex < 1 || nextIndex >= current.length)
        return current
      const next = [...current]
      ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
      return next
    })
  }
  const saveColumns = async () => {
    const columns = draftColumns.includes('id')
      ? draftColumns
      : ['id', ...draftColumns]
    setColumnsSaving(true)
    const response = await authenticatedFetch(
      `/api/can-sr/citations/workspace/preferences?sr_id=${encodeURIComponent(srId)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ columns }),
      },
    )
    setColumnsSaving(false)
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      setWorkspaceError(data?.error || data?.detail || copy.gridFailed)
      return
    }
    setVisibleColumns(columns)
    setPage(1)
    setColumnsOpen(false)
  }

  return (
    <>
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h4 className="text-lg font-semibold">{copy.gridTitle}</h4>
            <p className="mt-1 text-sm text-gray-600">
              {datasetReady ? copy.datasetReady : copy.empty}
            </p>
          </div>
          <Link
            className="rounded-md border px-3 py-2 text-sm font-medium"
            href={`/can-sr/search?sr_id=${encodeURIComponent(srId)}`}
          >
            {copy.databaseSearch}
          </Link>
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white"
          >
            <Plus className="h-4 w-4" />
            {copy.add}
          </button>
          {datasetReady ? (
            <button
              type="button"
              onClick={openColumns}
              className="rounded-md border px-3 py-2 text-sm font-medium"
            >
              {copy.columns}
            </button>
          ) : null}
          {selectedIds.length ? (
            <button
              type="button"
              onClick={() => void deleteSelected()}
              disabled={deleting}
              className="rounded-md bg-red-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              {deleting
                ? copy.working
                : copy.deleteSelected.replace(
                    '{count}',
                    String(selectedIds.length),
                  )}
            </button>
          ) : null}
        </div>
        {!datasetReady ? (
          <p className="mt-6 rounded-md border border-dashed p-5 text-sm text-gray-600">
            {copy.empty}
          </p>
        ) : (
          <div className="mt-6 space-y-3">
            <label className="block text-sm font-medium">
              {copy.search}
              <input
                className="mt-1 block w-full rounded-md border px-3 py-2 font-normal"
                type="search"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  setPage(1)
                }}
              />
            </label>
            {workspaceLoading ? (
              <p role="status" className="text-sm text-gray-600">
                {copy.loading}
              </p>
            ) : null}
            {workspaceError ? (
              <p role="alert" className="text-sm text-red-700">
                {workspaceError}
              </p>
            ) : null}
            {workspace && !workspaceLoading ? (
              workspace.citations.length ? (
                <div className="overflow-x-auto rounded-md border">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-gray-100 text-gray-700">
                      <tr>
                        <th className="px-3 py-2">
                          <Checkbox
                            aria-label={
                              copy.selectAll ||
                              'Select all citations on this page'
                            }
                            checked={
                              workspace.citations.length > 0 &&
                              workspace.citations.every((citation) =>
                                selectedIds.includes(Number(citation.id)),
                              )
                            }
                            onCheckedChange={(checked) => {
                              const pageIds = workspace.citations.map(
                                (citation) => Number(citation.id),
                              )
                              setSelectedIds((current) =>
                                checked
                                  ? [...new Set([...current, ...pageIds])]
                                  : current.filter(
                                      (id) => !pageIds.includes(id),
                                    ),
                              )
                            }}
                          />
                        </th>
                        {workspace.columns.map((column) => (
                          <th key={column} className="px-3 py-2 font-semibold">
                            <button
                              type="button"
                              onClick={() => toggleSort(column)}
                              className="inline-flex items-center gap-1 hover:underline"
                              aria-label={copy.sortBy.replace(
                                '{column}',
                                column,
                              )}
                            >
                              {column}
                              {sort === column
                                ? direction === 'asc'
                                  ? ' ↑'
                                  : ' ↓'
                                : ''}
                            </button>
                            <input
                              aria-label={(
                                copy.filterBy || 'Filter by {column}'
                              ).replace('{column}', column)}
                              className="mt-1 block w-full rounded border px-2 py-1 text-xs font-normal"
                              value={filters[column] || ''}
                              onChange={(event) => {
                                setFilters((current) => ({
                                  ...current,
                                  [column]: event.target.value,
                                }))
                                setPage(1)
                              }}
                            />
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {workspace.citations.map((citation, index) => (
                        <tr
                          key={String(citation.id || index)}
                          className="border-t"
                        >
                          <td className="px-3 py-2">
                            <Checkbox
                              aria-label={(
                                copy.selectCitation || 'Select citation {id}'
                              ).replace('{id}', String(citation.id))}
                              checked={selectedIds.includes(
                                Number(citation.id),
                              )}
                              onCheckedChange={() =>
                                toggleSelected(Number(citation.id))
                              }
                            />
                          </td>
                          {workspace.columns.map((column) => (
                            <td
                              key={column}
                              className="max-w-md truncate px-3 py-2"
                            >
                              {String(citation[column] ?? '')}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="rounded-md border border-dashed p-5 text-sm text-gray-600">
                  {copy.noMatches}
                </p>
              )
            ) : null}
            {workspace && workspace.total_count > workspace.page_size ? (
              <div className="flex items-center justify-between text-sm">
                <span>
                  {copy.results.replace(
                    '{count}',
                    String(workspace.total_count),
                  )}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="rounded border px-3 py-1 disabled:opacity-40"
                    disabled={page === 1}
                    onClick={() => setPage(page - 1)}
                  >
                    {copy.previous}
                  </button>
                  <button
                    type="button"
                    className="rounded border px-3 py-1 disabled:opacity-40"
                    disabled={
                      page * workspace.page_size >= workspace.total_count
                    }
                    onClick={() => setPage(page + 1)}
                  >
                    {copy.next}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </section>
      <Dialog open={columnsOpen} onOpenChange={setColumnsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy.columnsTitle}</DialogTitle>
            <DialogDescription>{copy.columnsDescription}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {(workspace?.available_columns || workspace?.columns || []).map(
              (column) => (
                <div key={column} className="flex items-center gap-2 text-sm">
                  <label className="flex items-center gap-2">
                    <Checkbox
                      checked={draftColumns.includes(column)}
                      disabled={column === 'id'}
                      onCheckedChange={() => toggleColumn(column)}
                    />
                    {column}
                  </label>
                  {draftColumns.includes(column) && column !== 'id' ? (
                    <span className="ml-auto flex gap-1">
                      <button
                        type="button"
                        onClick={() => moveColumn(column, -1)}
                        disabled={draftColumns.indexOf(column) <= 1}
                        className="rounded border px-1 disabled:opacity-40"
                        aria-label={copy.moveColumnUp.replace(
                          '{column}',
                          column,
                        )}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        onClick={() => moveColumn(column, 1)}
                        disabled={
                          draftColumns.indexOf(column) ===
                          draftColumns.length - 1
                        }
                        className="rounded border px-1 disabled:opacity-40"
                        aria-label={copy.moveColumnDown.replace(
                          '{column}',
                          column,
                        )}
                      >
                        ↓
                      </button>
                    </span>
                  ) : null}
                </div>
              ),
            )}
          </div>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setColumnsOpen(false)}
              className="rounded-md border px-4 py-2 text-sm"
            >
              {copy.cancel}
            </button>
            <button
              type="button"
              disabled={columnsSaving || draftColumns.length === 0}
              onClick={() => void saveColumns()}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              {columnsSaving ? copy.working : copy.saveColumns}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) void close()
          else setOpen(true)
        }}
      >
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{copy.dialogTitle}</DialogTitle>
            <DialogDescription>{copy.dialogDescription}</DialogDescription>
          </DialogHeader>
          <label className="block text-sm font-medium">
            {copy.file}
            <input
              className="mt-2 block w-full text-sm"
              type="file"
              accept=".csv,.ris,.txt,text/csv,text/plain,application/x-research-info-systems"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </label>
          {warnings.length ? (
            <ul className="list-disc space-y-1 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          {message ? (
            <p role="status" className="text-sm text-red-700">
              {message}
            </p>
          ) : null}
          <DialogFooter>
            <button
              type="button"
              onClick={() => void close()}
              className="rounded-md border px-4 py-2 text-sm"
            >
              {copy.cancel}
            </button>
            <button
              type="button"
              disabled={!file || busy}
              onClick={() => void importFile()}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy ? copy.working : copy.import || 'Import references'}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
