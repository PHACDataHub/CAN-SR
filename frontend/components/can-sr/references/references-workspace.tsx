'use client'

import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  CircleX,
  CornerDownLeft,
  Eye,
  EyeOff,
  Filter,
  Loader2,
  Plus,
  RefreshCw,
  Settings,
  Play,
} from 'lucide-react'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

type Props = {
  srId: string
  hasDataset: boolean | null
  copy: Record<string, string>
}

type Citation = Record<string, unknown>

type WorkspacePage = {
  citations: Citation[]
  total_count: number
  columns: string[]
  available_columns?: string[]
  sort: string
  direction: 'asc' | 'desc'
  query_fingerprint: string
  duplicate_fields?: string[]
  duplicate_counts?: Record<string, number>
  duplicate_groups?: Array<{
    group_id: string
    citation_ids: number[]
    status: string
    members: Citation[]
    suggested_survivor_id?: number | null
    survivor_reason?: string | null
    review?: DuplicateReview | null
  }>
  dataset_revision?: unknown
  duplicate_run?: {
    run_id?: string | null
    status?: 'succeeded' | 'not_run'
  }
}

type DuplicateReview = {
  group_id: string
  decision: 'confirmed_duplicate' | 'not_duplicate' | 'deferred'
  survivor_id?: number | null
  stale?: boolean
}

type DuplicateGroup = NonNullable<WorkspacePage['duplicate_groups']>[number]

const memberIds = (group: DuplicateGroup) =>
  group.members
    .map((member) => Number(member.id))
    .filter((id) => Number.isFinite(id))

const validMemberId = (group: DuplicateGroup, id: unknown) => {
  const numericId = Number(id)
  return memberIds(group).includes(numericId) ? numericId : undefined
}

export default function ReferencesWorkspace({ srId, hasDataset, copy }: Props) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [importColumns, setImportColumns] = useState<string[]>([])
  const [titleImportColumn, setTitleImportColumn] = useState('')
  const [abstractImportColumn, setAbstractImportColumn] = useState('')
  const [selectedImportColumns, setSelectedImportColumns] = useState<string[]>(
    [],
  )
  const [includeDuplicates, setIncludeDuplicates] = useState(false)
  const [hasDuplicates, setHasDuplicates] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [workspace, setWorkspace] = useState<WorkspacePage | null>(null)
  const [workspaceError, setWorkspaceError] = useState('')
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [draftSearch, setDraftSearch] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [draftFilters, setDraftFilters] = useState<Record<string, string>>({})
  const [openFilter, setOpenFilter] = useState<string | null>(null)
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({})
  const [resizingColumn, setResizingColumn] = useState<string | null>(null)
  const resizeStart = useRef<{
    column: string
    x: number
    width: number
  } | null>(null)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [deleting, setDeleting] = useState(false)
  const [sort, setSort] = useState('id')
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc')
  const [visibleColumns, setVisibleColumns] = useState<string[] | null>(null)
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [draftColumns, setDraftColumns] = useState<string[]>([])
  const [datasetReady, setDatasetReady] = useState(Boolean(hasDataset))
  const [selectedDatabase, setSelectedDatabase] = useState('')
  const [searchStrings, setSearchStrings] = useState<Record<string, string>>({})
  const [duplicateStatus, setDuplicateStatus] = useState('')
  const [duplicateFilterOpen, setDuplicateFilterOpen] = useState(false)
  const [draftDuplicateStatus, setDraftDuplicateStatus] = useState('')
  const [dedupOpen, setDedupOpen] = useState(false)
  const [dedupFields, setDedupFields] = useState<string[]>([])
  const [matchingThreshold, setMatchingThreshold] = useState(0.7)
  const [draftDedupFields, setDraftDedupFields] = useState<string[]>([])
  const [dedupRunning, setDedupRunning] = useState(false)
  const [dedupRunStatus, setDedupRunStatus] = useState<
    'not_run' | 'succeeded' | 'stale'
  >('not_run')
  const [reviewGroupIndex, setReviewGroupIndex] = useState(0)
  const [reviews, setReviews] = useState<DuplicateReview[]>([])
  const [selectedSurvivors, setSelectedSurvivors] = useState<
    Record<string, number>
  >({})
  const [reviewMinimized, setReviewMinimized] = useState(true)
  const [reviewSaving, setReviewSaving] = useState(false)
  const [selectionMenuOpen, setSelectionMenuOpen] = useState(false)

  useEffect(() => {
    setDatasetReady(Boolean(hasDataset))
  }, [hasDataset])

  useEffect(() => {
    const dismiss = (event: MouseEvent) => {
      const target = event.target as Node
      if (!(target as HTMLElement).closest('[data-reference-popover]')) {
        setColumnsOpen(false)
        setDedupOpen(false)
        setDuplicateFilterOpen(false)
        setOpenFilter(null)
      }
    }
    document.addEventListener('mousedown', dismiss)
    return () => document.removeEventListener('mousedown', dismiss)
  }, [])

  const loadWorkspace = async () => {
    if (!datasetReady) {
      setWorkspace(null)
      return
    }
    setWorkspaceLoading(true)
    setWorkspaceError('')
    const params = new URLSearchParams({
      sr_id: srId,
      sort,
      direction,
    })
    if (search.trim()) params.set('search', search.trim())
    const activeFilters = Object.fromEntries(
      Object.entries(filters).filter(([, value]) => value.trim()),
    )
    if (Object.keys(activeFilters).length)
      params.set('filters', JSON.stringify(activeFilters))
    if (duplicateStatus) params.set('duplicate_status', duplicateStatus)
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
    setDedupRunStatus((current) =>
      current === 'stale'
        ? 'stale'
        : data?.duplicate_run?.status === 'succeeded'
          ? 'succeeded'
          : 'not_run',
    )
  }

  useEffect(() => {
    void loadWorkspace()
    // loadWorkspace intentionally tracks the request inputs rather than its identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    srId,
    datasetReady,
    search,
    filters,
    sort,
    direction,
    visibleColumns,
    duplicateStatus,
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
      const dedupResponse = await authenticatedFetch(
        `/api/can-sr/citations/workspace/deduplication-preferences?sr_id=${encodeURIComponent(srId)}`,
      )
      const dedupData = await dedupResponse.json().catch(() => ({}))
      if (dedupResponse.ok && Array.isArray(dedupData?.fields)) {
        setDedupFields(dedupData.fields)
      }
      if (
        dedupResponse.ok &&
        [0.5, 0.7, 0.8].includes(Number(dedupData?.threshold))
      ) {
        setMatchingThreshold(Number(dedupData.threshold))
      }
      const reviewResponse = await authenticatedFetch(
        `/api/can-sr/citations/workspace/duplicate-reviews?sr_id=${encodeURIComponent(srId)}`,
      )
      const reviewData = await reviewResponse.json().catch(() => ({}))
      if (reviewResponse.ok && Array.isArray(reviewData?.reviews))
        setReviews(reviewData.reviews)
    })()
  }, [srId, datasetReady])

  useEffect(() => {
    setSelectedIds([])
    setReviewGroupIndex(0)
  }, [search, filters, sort, direction, visibleColumns, duplicateStatus])

  useEffect(() => {
    const groups = workspace?.duplicate_groups || []
    if (!groups.length) {
      setReviewGroupIndex(0)
      return
    }
    setReviewGroupIndex((current) => {
      return Math.min(current, groups.length - 1)
    })
  }, [workspace, reviews])

  useEffect(() => {
    const groups = workspace?.duplicate_groups || []
    if (!groups.length) {
      setSelectedSurvivors({})
      return
    }
    setSelectedSurvivors((current) => {
      const next: Record<string, number> = {}
      for (const group of groups) {
        const savedReview =
          group.review ||
          reviews.find((review) => review.group_id === group.group_id)
        const selected =
          validMemberId(group, current[group.group_id]) ??
          validMemberId(group, savedReview?.survivor_id) ??
          validMemberId(group, group.suggested_survivor_id) ??
          memberIds(group)[0]
        if (selected !== undefined) next[group.group_id] = selected
      }
      return next
    })
  }, [workspace, reviews])

  const close = () => {
    setOpen(false)
    setFile(null)
    setImportColumns([])
    setTitleImportColumn('')
    setAbstractImportColumn('')
    setSelectedImportColumns([])
    setIncludeDuplicates(false)
    setHasDuplicates(false)
    setWarnings([])
    setMessage('')
    setSelectedDatabase('')
    setSearchStrings({})
  }

  const searchDatabases = async () => {
    if (!selectedDatabase) return
    setBusy(true)
    setMessage('')
    const response = await authenticatedFetch(
      `/api/can-sr/search?sr_id=${encodeURIComponent(srId)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          database: selectedDatabase,
          search_term: searchStrings[selectedDatabase] || '',
        }),
      },
    )
    const data = await response.json().catch(() => ({}))
    setBusy(false)
    setMessage(
      response.ok
        ? data?.message || copy.searchCompleted || 'Database search completed.'
        : data?.error ||
            data?.detail ||
            copy.searchFailed ||
            'Database search failed.',
    )
  }

  const applyFilter = (column: string) => {
    setFilters((current) => ({
      ...current,
      [column]: (draftFilters[column] || '').trim(),
    }))
    setOpenFilter(null)
  }

  const clearFilter = (column: string) => {
    setDraftFilters((current) => ({ ...current, [column]: '' }))
    setFilters((current) => {
      const next = { ...current }
      delete next[column]
      return next
    })
    setOpenFilter(null)
  }

  const beginResize = (
    column: string,
    event: React.PointerEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    resizeStart.current = {
      column,
      x: event.clientX,
      width: columnWidths[column] || 160,
    }
    setResizingColumn(column)
    window.addEventListener('pointermove', resizeColumn)
    window.addEventListener('pointerup', endResize)
    window.addEventListener('pointercancel', endResize)
  }

  const resizeColumn = (event: PointerEvent) => {
    const start = resizeStart.current
    if (!start) return
    setColumnWidths((current) => ({
      ...current,
      [start.column]: Math.max(96, start.width + event.clientX - start.x),
    }))
  }

  const endResize = () => {
    resizeStart.current = null
    setResizingColumn(null)
    window.removeEventListener('pointermove', resizeColumn)
    window.removeEventListener('pointerup', endResize)
    window.removeEventListener('pointercancel', endResize)
  }

  const tableWidth =
    280 +
    (workspace?.columns || []).reduce(
      (total, column) => total + (columnWidths[column] || 160),
      0,
    )

  const parseImportColumns = async (selectedFile: File | null) => {
    if (!selectedFile) {
      setImportColumns([])
      setSelectedImportColumns([])
      return
    }
    const headers = selectedFile.name.toLowerCase().endsWith('.csv')
      ? ((await selectedFile.text()).split(/\r?\n/, 1)[0] || '')
          .split(',')
          .map((value) => value.trim().replace(/^"|"$/g, ''))
          .filter(Boolean)
      : ['Title', 'Abstract', 'Keywords', 'Journal', 'Year', 'Authors', 'DOI', 'Type', 'URL']
    setImportColumns(headers)
    setTitleImportColumn('')
    setAbstractImportColumn('')
    setSelectedImportColumns((current) =>
      current.length
        ? current.filter((column) => headers.includes(column))
        : headers.filter((column) => !['id', 'provenance'].includes(column)),
    )
  }

  const importFile = async () => {
    if (!file) return
    setBusy(true)
    setMessage('')
    const form = new FormData()
    form.append('file', file)
    form.append('commit_key', crypto.randomUUID())
    form.append('include_duplicates', String(includeDuplicates))
    if (!titleImportColumn || !abstractImportColumn) {
      setMessage('Select the source columns to use for Title and Abstract before importing.')
      setBusy(false)
      return
    }
    form.append('title_header', titleImportColumn)
    form.append('abstract_header', abstractImportColumn)
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
    const importedMessage = (
      copy.imported || 'Import complete: {count} citations added.'
    ).replace('{count}', String(data.rows_inserted))
    setMessage(
      data.duplicates_skipped
        ? `${importedMessage} ${(
            copy.duplicatesSkipped || '{count} duplicates skipped.'
          ).replace('{count}', String(data.duplicates_skipped))}`
        : importedMessage,
    )
    if (selectedImportColumns.length) {
      const columns = [
        'id',
        ...selectedImportColumns.filter((column) => column !== 'id'),
      ]
      await authenticatedFetch(
        `/api/can-sr/citations/workspace/preferences?sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ columns }),
        },
      )
      await authenticatedFetch(
        `/api/can-sr/citations/workspace/deduplication-preferences?sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fields: selectedImportColumns,
            threshold: matchingThreshold,
          }),
        },
      )
      setVisibleColumns(columns)
      setDedupFields(selectedImportColumns)
    }
    setDatasetReady(true)
    await loadWorkspace()
    setFile(null)
  }

  const checkFileForDuplicates = async (selectedFile: File | null) => {
    setHasDuplicates(false)
    setIncludeDuplicates(false)
    if (!selectedFile) return
    const form = new FormData()
    form.append('file', selectedFile)
    const response = await authenticatedFetch(
      `/api/can-sr/citations/duplicates/check?sr_id=${encodeURIComponent(srId)}`,
      { method: 'POST', body: form },
    )
    const data = await response.json().catch(() => ({}))
    if (response.ok) {
      const duplicateCount = Number(data.duplicates_count)
      setHasDuplicates(duplicateCount > 0)
      setWarnings((current) =>
        duplicateCount > 0
          ? [
              ...current.filter(
                (warning) => !warning.includes('__duplicate_warning__'),
              ),
              `__duplicate_warning__${(
                copy.duplicatesDetected ||
                '{count} duplicate references detected. They will be merged unless Import Duplicates is selected.'
              ).replace('{count}', String(duplicateCount))}`,
            ]
          : current.filter(
              (warning) => !warning.includes('__duplicate_warning__'),
            ),
      )
    }
  }

  const toggleSort = (column: string) => {
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
  const queryPayload = () => ({
    search: search.trim() || undefined,
    sort,
    direction,
    columns: visibleColumns,
    filters: Object.fromEntries(
      Object.entries(filters).filter(([, value]) => value.trim()),
    ),
    duplicate_status: duplicateStatus || undefined,
  })
  const deleteSelected = async (ids = selectedIds, advanceReview = false) => {
    if (!ids.length) return false
    setDeleting(true)
    const response = await authenticatedFetch(
      `/api/can-sr/citations/workspace?sr_id=${encodeURIComponent(srId)}`,
      {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          citation_ids: ids,
          query_fingerprint: workspace?.query_fingerprint,
          query: queryPayload(),
          confirmed: true,
        }),
      },
    )
    const data = await response.json().catch(() => ({}))
    setDeleting(false)
    if (!response.ok) {
      setWorkspaceError(data?.error || data?.detail || copy.deleteFailed)
      return false
    }
    setSelectedIds([])
    await loadWorkspace()
    if (advanceReview) setReviewGroupIndex((index) => index + 1)
    return true
  }
  const saveReview = async (
    groupId: string,
    decision: DuplicateReview['decision'],
    survivorId?: number,
  ) => {
    setReviewSaving(true)
    const response = await authenticatedFetch(
      `/api/can-sr/citations/workspace/duplicate-reviews?sr_id=${encodeURIComponent(srId)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          group_id: groupId,
          decision,
          survivor_id: survivorId,
        }),
      },
    )
    const data = await response.json().catch(() => ({}))
    setReviewSaving(false)
    if (!response.ok) {
      setWorkspaceError(data?.error || data?.detail || copy.gridFailed)
      return
    }
    setReviews((current) => [
      ...current.filter((review) => review.group_id !== groupId),
      data,
    ])
    await loadWorkspace()
  }
  const getReviewSurvivor = (group: DuplicateGroup) => {
    const savedReview =
      group.review ||
      reviews.find((review) => review.group_id === group.group_id)
    return (
      validMemberId(group, selectedSurvivors[group.group_id]) ??
      validMemberId(group, savedReview?.survivor_id) ??
      validMemberId(group, group.suggested_survivor_id) ??
      memberIds(group)[0]
    )
  }
  const openDuplicateGroup = (groupId: unknown) => {
    const visibleIds = new Set(
      (workspace?.citations || []).map((citation) => Number(citation.id)),
    )
    const reviewGroups = (workspace?.duplicate_groups || []).filter((group) =>
      group.citation_ids.some((id) => visibleIds.has(Number(id))),
    )
    const groupIndex = reviewGroups.findIndex(
      (group) => group.group_id === String(groupId),
    )
    if (groupIndex >= 0) {
      setReviewMinimized(false)
      setReviewGroupIndex(groupIndex)
    }
  }
  const openColumns = () => {
    setDraftColumns(workspace?.columns || visibleColumns || ['id'])
    setColumnsOpen((current) => !current)
  }
  const openDeduplication = () => {
    setDraftDedupFields(
      dedupFields.length
        ? dedupFields
        : workspace?.columns.filter(
            (column) => column !== 'id' && column !== 'provenance',
          ) || [],
    )
    setDedupOpen((current) => !current)
  }
  const persistColumnPreferences = async (
    columns: string[],
    fields: string[],
    threshold = matchingThreshold,
  ) => {
    const [columnsResponse, dedupResponse] = await Promise.all([
      authenticatedFetch(
        `/api/can-sr/citations/workspace/preferences?sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ columns }),
        },
      ),
      authenticatedFetch(
        `/api/can-sr/citations/workspace/deduplication-preferences?sr_id=${encodeURIComponent(srId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fields, threshold }),
        },
      ),
    ])
    if (!columnsResponse.ok || !dedupResponse.ok) {
      const response = !columnsResponse.ok ? columnsResponse : dedupResponse
      const data = await response.json().catch(() => ({}))
      setWorkspaceError(data?.error || data?.detail || copy.gridFailed)
      return false
    }
    setDedupRunStatus('stale')
    return true
  }
  const runDeduplication = async () => {
    setDedupRunning(true)
    setWorkspaceError('')
    const response = await authenticatedFetch(
      `/api/can-sr/citations/workspace/duplicate-runs?sr_id=${encodeURIComponent(srId)}`,
      { method: 'POST' },
    )
    const data = await response.json().catch(() => ({}))
    setDedupRunning(false)
    if (!response.ok) {
      setWorkspaceError(data?.error || data?.detail || copy.gridFailed)
      return
    }
    setDedupRunStatus('succeeded')
    await loadWorkspace()
  }
  const openDuplicateFilter = () => {
    setDraftDuplicateStatus(duplicateStatus)
    setDuplicateFilterOpen((current) => !current)
  }
  const applyDuplicateFilter = () => {
    setDuplicateStatus(draftDuplicateStatus)
    setDuplicateFilterOpen(false)
  }
  const toggleColumn = (column: string) => {
    if (column === 'id') return
    const currentColumns = workspace?.columns || visibleColumns || ['id']
    const nextColumns = currentColumns.includes(column)
      ? currentColumns.filter((value) => value !== column)
      : [...currentColumns, column]
    const nextFields = nextColumns.filter(
      (value) => value !== 'id' && value !== 'provenance',
    )
    setDraftColumns(nextColumns)
    setVisibleColumns(nextColumns)
    setDedupFields(nextFields)
    void persistColumnPreferences(nextColumns, nextFields)
  }
  const moveColumn = (column: string, offset: -1 | 1) => {
    const current = workspace?.columns || visibleColumns || ['id']
    const index = current.indexOf(column)
    const nextIndex = index + offset
    if (index < 0 || nextIndex < 1 || nextIndex >= current.length) return
    const next = [...current]
    ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
    setDraftColumns(next)
    setVisibleColumns(next)
    void persistColumnPreferences(
      next,
      next.filter((value) => value !== 'id' && value !== 'provenance'),
    )
  }
  const setMatchingStrength = (threshold: number) => {
    setMatchingThreshold(threshold)
    void authenticatedFetch(
      `/api/can-sr/citations/workspace/deduplication-preferences?sr_id=${encodeURIComponent(srId)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fields: dedupFields,
          threshold,
        }),
      },
    ).then(async (response) => {
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        setWorkspaceError(data?.error || data?.detail || copy.gridFailed)
        return
      }
      setDedupRunStatus('stale')
    })
  }

  return (
    <>
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h4 className="text-lg font-semibold">{copy.gridTitle}</h4>
            <p className="mt-1 text-sm text-gray-600">
              {datasetReady ? copy.datasetReady : copy.empty}
            </p>
          </div>
          {datasetReady ? (
            <div className="flex w-full flex-wrap items-end gap-2 sm:w-auto sm:flex-nowrap">
              <div className="min-w-0 flex-1 sm:w-80 sm:flex-none">
                <label
                  htmlFor="reference-search"
                  className="mb-1 block text-xs font-semibold text-gray-700"
                >
                  {copy.search}
                </label>
                <div className="relative">
                  <input
                    id="reference-search"
                    className="block h-9 w-full rounded-md border px-2.5 pr-20 text-sm font-normal"
                    type="search"
                    value={draftSearch}
                    onChange={(event) => {
                      const nextSearch = event.target.value
                      setDraftSearch(nextSearch)
                      if (!nextSearch.trim()) {
                        setSearch('')
                      }
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        setSearch(draftSearch)
                      }
                    }}
                  />
                  {draftSearch.trim() ? (
                    <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center gap-1 text-[11px] text-gray-500">
                      <CornerDownLeft
                        className="h-3.5 w-3.5"
                        aria-hidden="true"
                      />
                      <kbd className="rounded border border-gray-300 bg-gray-50 px-1.5 py-0.5 font-sans text-[10px] leading-none font-medium">
                        Enter
                      </kbd>
                    </span>
                  ) : null}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setOpen(true)}
                className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md bg-emerald-600 px-3 text-sm font-medium text-white"
              >
                <Plus className="h-3.5 w-3.5" />
                {copy.add}
              </button>
              {selectedIds.length ? (
                <button
                  type="button"
                  onClick={() => void deleteSelected()}
                  disabled={deleting}
                  className="inline-flex h-9 shrink-0 items-center rounded-md bg-red-700 px-3 text-sm font-medium text-white disabled:opacity-40"
                >
                  {deleting
                    ? copy.deleting
                    : copy.deleteSelected.replace(
                        '{count}',
                        String(selectedIds.length),
                      )}
                </button>
              ) : null}
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md bg-emerald-600 px-3 text-sm font-medium text-white"
            >
              <Plus className="h-3.5 w-3.5" />
              {copy.add}
            </button>
          )}
        </div>
        {!datasetReady ? (
          <p className="mt-6 rounded-md border border-dashed p-5 text-sm text-gray-600">
            {copy.empty}
          </p>
        ) : (
          <div className="mt-5 space-y-3">
            {workspaceLoading && !workspace ? (
              <p role="status" className="text-sm text-gray-600">
                {copy.loading}
              </p>
            ) : null}
            {workspaceError ? (
              <p role="alert" className="text-sm text-red-700">
                {workspaceError}
              </p>
            ) : null}
            {workspace ? (
              <>
                {(() => {
                  const visibleIds = new Set(
                    workspace.citations.map((citation) => Number(citation.id)),
                  )
                  const reviewGroups = (
                    workspace.duplicate_groups || []
                  ).filter((group) =>
                    group.citation_ids.some((id) => visibleIds.has(Number(id))),
                  )
                  const reviewGroup = reviewGroups[reviewGroupIndex]
                  return reviewGroup ? (
                    <section
                      aria-label={copy.duplicateGroupReview}
                      className="rounded-md border border-amber-200 bg-amber-50 p-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <h2 className="font-medium text-amber-950">
                            {copy.duplicateGroupReview}
                          </h2>
                          <p className="text-xs text-amber-900">
                            {copy.groupSummary
                              .replace(
                                '{current}',
                                String(reviewGroupIndex + 1),
                              )
                              .replace('{total}', String(reviewGroups.length))
                              .replace('{status}', reviewGroup.status)
                              .replace(
                                '{count}',
                                String(reviewGroup.members.length),
                              )}
                          </p>
                        </div>
                        <div>
                          <button
                            type="button"
                            className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-amber-300 bg-amber-100 text-amber-950 shadow-sm transition-colors hover:bg-amber-200 hover:text-amber-950 focus:ring-2 focus:ring-amber-700 focus:ring-offset-1 focus:outline-none disabled:opacity-50"
                            onClick={() =>
                              setReviewMinimized((minimized) => !minimized)
                            }
                            aria-expanded={!reviewMinimized}
                            aria-label={`${reviewMinimized ? copy.restore : copy.minimize} ${copy.duplicateGroupReview}`}
                            title={`${reviewMinimized ? copy.restore : copy.minimize} ${copy.duplicateGroupReview}`}
                          >
                            {reviewMinimized ? (
                              <ChevronDown
                                className="h-6 w-6 stroke-[2.5]"
                                aria-hidden="true"
                              />
                            ) : (
                              <ChevronUp
                                className="h-6 w-6 stroke-[2.5]"
                                aria-hidden="true"
                              />
                            )}
                          </button>
                        </div>
                      </div>
                      {!reviewMinimized ? (
                        <>
                          <div className="mt-3 grid gap-2 md:grid-cols-2">
                            {reviewGroup.members.map((member) => (
                              <article
                                key={String(member.id)}
                                className="rounded border bg-white p-2 text-xs"
                              >
                                <div className="flex items-center justify-between font-medium">
                                  <span>
                                    {copy.record.replace(
                                      '{id}',
                                      String(member.id),
                                    )}
                                  </span>
                                  <span>
                                    {String(member.duplicate_score ?? '—')}
                                  </span>
                                </div>
                                <label className="mt-2 flex items-center gap-2 text-emerald-800">
                                  <input
                                    type="radio"
                                    name={`survivor-${reviewGroup.group_id}`}
                                    checked={
                                      getReviewSurvivor(reviewGroup) ===
                                      Number(member.id)
                                    }
                                    onChange={() => {
                                      const survivorId = Number(member.id)
                                      setSelectedSurvivors((current) => ({
                                        ...current,
                                        [reviewGroup.group_id]: survivorId,
                                      }))
                                      void saveReview(
                                        reviewGroup.group_id,
                                        'confirmed_duplicate',
                                        survivorId,
                                      )
                                    }}
                                  />
                                  {Number(member.id) ===
                                  reviewGroup.suggested_survivor_id
                                    ? copy.suggestedSurvivor
                                    : copy.selectSurvivor}
                                </label>
                                {workspace.duplicate_fields?.map((field) => (
                                  <div
                                    key={field}
                                    className="mt-1 grid grid-cols-[7rem_1fr] gap-2"
                                  >
                                    <span className="text-gray-500">
                                      {field}
                                    </span>
                                    <span className="break-words">
                                      {String(member[field] ?? '')}
                                    </span>
                                  </div>
                                ))}
                              </article>
                            ))}
                          </div>
                          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-amber-200 pt-3">
                            <span className="text-xs font-medium text-amber-950">
                              {copy.reviewDecision}
                            </span>
                            {(
                              [
                                ['confirmed_duplicate', copy.confirmDuplicate],
                                ['not_duplicate', copy.keepBoth],
                                ['deferred', copy.defer],
                              ] as const
                            ).map(([decision, label]) => {
                              const review =
                                reviewGroup.review ||
                                reviews.find(
                                  (item) =>
                                    item.group_id === reviewGroup.group_id,
                                )
                              if (
                                decision === 'confirmed_duplicate' &&
                                review?.decision === 'confirmed_duplicate'
                              ) {
                                const survivorId =
                                  getReviewSurvivor(reviewGroup)
                                const nonSurvivor = memberIds(reviewGroup).find(
                                  (id) => id !== survivorId,
                                )
                                return (
                                  <button
                                    key={decision}
                                    type="button"
                                    disabled={deleting || nonSurvivor == null}
                                    className="rounded bg-red-700 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
                                    onClick={() => {
                                      if (nonSurvivor == null) return
                                      void deleteSelected(
                                        [Number(nonSurvivor)],
                                        true,
                                      )
                                    }}
                                  >
                                    {copy.deleteCitation.replace(
                                      '{id}',
                                      String(nonSurvivor),
                                    )}
                                  </button>
                                )
                              }
                              return (
                                <button
                                  key={decision}
                                  type="button"
                                  disabled={reviewSaving}
                                  className={`rounded border px-2 py-1 text-xs disabled:opacity-50 ${review?.decision === decision ? 'border-emerald-600 bg-emerald-100 text-emerald-900' : 'bg-white'}`}
                                  onClick={() => {
                                    const survivor =
                                      getReviewSurvivor(reviewGroup)
                                    void saveReview(
                                      reviewGroup.group_id,
                                      decision,
                                      decision === 'confirmed_duplicate'
                                        ? survivor
                                        : undefined,
                                    )
                                  }}
                                >
                                  {label}
                                </button>
                              )
                            })}
                            {(
                              reviewGroup.review ||
                              reviews.find(
                                (item) =>
                                  item.group_id === reviewGroup.group_id,
                              )
                            )?.decision === 'confirmed_duplicate' ? (
                              <span className="text-xs text-amber-900">
                                {copy.survivor}:{' '}
                                {String(getReviewSurvivor(reviewGroup) ?? '')}
                              </span>
                            ) : null}
                            {(
                              reviewGroup.review ||
                              reviews.find(
                                (item) =>
                                  item.group_id === reviewGroup.group_id,
                              )
                            )?.stale ? (
                              <span className="text-xs text-red-700">
                                {copy.staleSurvivor ||
                                  'The saved survivor is no longer in this group; a current member was selected.'}
                              </span>
                            ) : null}
                            <div className="ml-auto flex gap-2">
                              <button
                                type="button"
                                className="rounded border bg-white px-2 py-1 text-xs disabled:opacity-50"
                                disabled={reviewGroupIndex === 0}
                                onClick={() =>
                                  setReviewGroupIndex((index) => index - 1)
                                }
                              >
                                {copy.previous}
                              </button>
                              <button
                                type="button"
                                className="rounded border bg-white px-2 py-1 text-xs disabled:opacity-50"
                                disabled={
                                  reviewGroupIndex >= reviewGroups.length - 1
                                }
                                onClick={() =>
                                  setReviewGroupIndex((index) => index + 1)
                                }
                              >
                                {copy.next}
                              </button>
                            </div>
                          </div>
                        </>
                      ) : null}
                    </section>
                  ) : null
                })()}
                <div className="max-h-[70vh] overflow-auto rounded-md border">
                  <table
                    className="min-w-full table-fixed text-left text-sm"
                    style={{ width: tableWidth }}
                  >
                    <colgroup>
                      <col style={{ width: 48 }} />
                      <col style={{ width: 48 }} />
                      <col style={{ width: 88 }} />
                      {workspace.columns.map((column) => (
                        <col
                          key={column}
                          style={{ width: columnWidths[column] || 160 }}
                        />
                      ))}
                      <col style={{ width: 48 }} />
                      <col style={{ width: 48 }} />
                    </colgroup>
                    <thead className="sticky top-0 z-10 bg-gray-100 text-gray-700">
                      <tr>
                        <th className="w-12 px-3 py-2 text-right font-normal text-gray-500">
                          #
                        </th>
                        <th className="w-12 px-3 py-2">
                          <div className="relative flex items-center gap-1">
                            <Checkbox
                              aria-label={copy.selectAll}
                              checked={
                                workspace.citations.length > 0 &&
                                workspace.citations.every((citation) =>
                                  selectedIds.includes(Number(citation.id)),
                                )
                              }
                              onCheckedChange={() => setSelectionMenuOpen(true)}
                            />
                            {selectionMenuOpen ? (
                              <div
                                data-reference-popover
                                className="absolute top-full left-0 z-30 w-48 rounded-md border bg-white p-1 text-left font-normal shadow-lg"
                              >
                                {[
                                  [copy.none, []],
                                  [
                                    copy.all,
                                    workspace.citations.map((citation) =>
                                      Number(citation.id),
                                    ),
                                  ],
                                  [
                                    copy.suggestedDuplicates,
                                    (workspace.duplicate_groups || []).flatMap(
                                      (group) =>
                                        group.citation_ids
                                          .map(Number)
                                          .filter(
                                            (id) =>
                                              id !== getReviewSurvivor(group),
                                          ),
                                    ),
                                  ],
                                ].map(([label, ids]) => (
                                  <button
                                    key={String(label)}
                                    type="button"
                                    className="block w-full rounded px-2 py-1 text-left text-sm hover:bg-gray-100"
                                    onClick={() => {
                                      setSelectedIds(ids as number[])
                                      setSelectionMenuOpen(false)
                                    }}
                                  >
                                    {String(label)}
                                  </button>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </th>
                        <th className="relative w-[88px] px-4 py-2 text-center">
                          <div className="flex items-center justify-center gap-2">
                            <button
                              type="button"
                              data-reference-popover
                              onClick={openDuplicateFilter}
                              className={`rounded p-1 ${duplicateStatus ? 'text-emerald-700' : 'text-gray-500'} hover:bg-gray-200`}
                              aria-label={
                                duplicateStatus
                                  ? `${copy.filterDuplicateStatus}: ${duplicateStatus}`
                                  : copy.showDuplicateStatusFilter
                              }
                              title={copy.filterDuplicateStatuses}
                            >
                              {duplicateStatus ? (
                                <Eye className="h-4 w-4" aria-hidden="true" />
                              ) : (
                                <EyeOff
                                  className="h-4 w-4"
                                  aria-hidden="true"
                                />
                              )}
                            </button>
                            {duplicateFilterOpen ? (
                              <div
                                data-reference-popover
                                className="absolute top-full left-0 z-30 w-64 rounded-md border bg-white p-3 text-left font-normal shadow-lg"
                              >
                                <p className="font-semibold">
                                  {copy.duplicateStatus}
                                </p>
                                <label
                                  className="mt-2 block text-xs text-gray-600"
                                  htmlFor="duplicate-status-filter"
                                >
                                  {copy.showReferencesMatching}
                                </label>
                                <select
                                  id="duplicate-status-filter"
                                  className="mt-1 w-full rounded border px-2 py-1 text-sm"
                                  value={draftDuplicateStatus}
                                  onChange={(event) =>
                                    setDraftDuplicateStatus(event.target.value)
                                  }
                                >
                                  <option value="">{copy.allStatuses}</option>
                                  <option value="exact">
                                    {copy.exactDuplicates}
                                  </option>
                                  <option value="possible">
                                    {copy.possibleDuplicates}
                                  </option>
                                  <option value="no_match">
                                    {copy.noDuplicateMatch}
                                  </option>
                                </select>
                                <div className="mt-3 flex justify-end gap-2">
                                  <button
                                    type="button"
                                    className="rounded border px-2 py-1 text-xs"
                                    onClick={() =>
                                      setDuplicateFilterOpen(false)
                                    }
                                  >
                                    {copy.cancel}
                                  </button>
                                  <button
                                    type="button"
                                    className="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white"
                                    onClick={applyDuplicateFilter}
                                  >
                                    {copy.applyFilter}
                                  </button>
                                </div>
                              </div>
                            ) : null}
                            <button
                              type="button"
                              data-reference-popover
                              onClick={openDeduplication}
                              className="rounded p-1 text-gray-500 hover:bg-gray-200"
                              aria-label={copy.configureDuplicateFields}
                              title={copy.configureDuplicateFields}
                            >
                              <Settings
                                className="h-4 w-4"
                                aria-hidden="true"
                              />
                            </button>
                            <button
                              type="button"
                              onClick={() => void runDeduplication()}
                              disabled={dedupRunning}
                              className={`rounded p-1 hover:bg-gray-200 ${dedupRunning ? 'text-emerald-700' : dedupRunStatus === 'stale' ? 'text-amber-600' : 'text-emerald-700'}`}
                              aria-label={
                                dedupRunning
                                  ? copy.runningDuplicateCalculation
                                  : dedupRunStatus === 'succeeded'
                                    ? copy.rerunDuplicateCalculation
                                    : dedupRunStatus === 'stale'
                                      ? copy.rerunDuplicateCalculation
                                      : copy.runDuplicateCalculation
                              }
                              title={
                                dedupRunning
                                  ? copy.runningDuplicateCalculation
                                  : dedupRunStatus === 'succeeded' ||
                                      dedupRunStatus === 'stale'
                                    ? copy.rerunDuplicateCalculation
                                    : copy.runDuplicateCalculation
                              }
                            >
                              {dedupRunning ? (
                                <Loader2
                                  className="h-4 w-4 animate-spin"
                                  aria-hidden="true"
                                />
                              ) : dedupRunStatus === 'succeeded' ? (
                                <RefreshCw
                                  className="h-4 w-4"
                                  aria-hidden="true"
                                />
                              ) : (
                                <Play className="h-4 w-4" aria-hidden="true" />
                              )}
                            </button>
                          </div>
                          {dedupOpen ? (
                            <div
                              data-reference-popover
                              className="absolute top-full left-0 z-30 w-72 rounded-md border bg-white p-3 text-left font-normal shadow-lg"
                            >
                              <h2 className="text-sm font-semibold text-gray-900">
                                {copy.deduplicationSettings ||
                                  'Deduplication Settings'}
                              </h2>
                              <fieldset className="mt-4">
                                <legend className="text-xs font-semibold text-gray-700">
                                  {copy.matchingStrength || 'Matching strength'}
                                </legend>
                                <div
                                  className="mt-2 grid grid-cols-3 rounded-md border border-gray-200 bg-gray-50 p-0.5"
                                  role="radiogroup"
                                  aria-label={
                                    copy.matchingStrength || 'Matching Strength'
                                  }
                                >
                                  {[
                                    [0.5, copy.permissive || 'Permissive'],
                                    [0.7, copy.balanced || 'Balanced'],
                                    [0.8, copy.strict || 'Strict'],
                                  ].map(([threshold, label]) => {
                                    const selected =
                                      matchingThreshold === threshold
                                    return (
                                      <button
                                        key={String(threshold)}
                                        type="button"
                                        role="radio"
                                        aria-checked={selected}
                                        onClick={() =>
                                          setMatchingStrength(Number(threshold))
                                        }
                                        className={`rounded px-1.5 py-1.5 text-xs font-medium transition-colors focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:outline-none ${selected ? 'bg-white text-emerald-700 shadow-sm ring-1 ring-gray-200' : 'text-gray-500 hover:bg-white/80 hover:text-gray-700'}`}
                                      >
                                        {String(label)}
                                      </button>
                                    )
                                  })}
                                </div>
                              </fieldset>
                              <h3 className="mt-4 border-t border-gray-100 pt-3 text-xs font-semibold text-gray-700">
                                {copy.selectDeduplicationFields ||
                                  'Select Deduplication Fields'}
                              </h3>
                              <div className="mt-2 max-h-56 space-y-1 overflow-auto">
                                {(
                                  workspace.available_columns ||
                                  workspace.columns
                                )
                                  .filter(
                                    (column) =>
                                      column !== 'id' &&
                                      column !== 'provenance',
                                  )
                                  .map((column) => (
                                    <label
                                      key={column}
                                      className="flex items-center gap-2 text-sm"
                                    >
                                      <Checkbox
                                        checked={draftDedupFields.includes(
                                          column,
                                        )}
                                        onCheckedChange={(checked) => {
                                          const currentColumns =
                                            workspace.columns || []
                                          const nextFields = checked
                                            ? [
                                                ...new Set([
                                                  ...dedupFields,
                                                  column,
                                                ]),
                                              ]
                                            : dedupFields.filter(
                                                (value) => value !== column,
                                              )
                                          const nextColumns = checked
                                            ? [
                                                ...new Set([
                                                  ...currentColumns,
                                                  column,
                                                ]),
                                              ]
                                            : currentColumns.filter(
                                                (value) => value !== column,
                                              )
                                          setDraftDedupFields(nextFields)
                                          setDedupFields(nextFields)
                                          setDraftColumns(nextColumns)
                                          setVisibleColumns(nextColumns)
                                          setDedupRunStatus('stale')
                                          void persistColumnPreferences(
                                            nextColumns,
                                            nextFields,
                                          )
                                        }}
                                      />
                                      {column}
                                    </label>
                                  ))}
                              </div>
                            </div>
                          ) : null}
                        </th>
                        {workspace.columns.map((column) => (
                          <th
                            key={column}
                            className="relative px-3 py-2 font-semibold"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <button
                                type="button"
                                onClick={() => toggleSort(column)}
                                className="inline-flex min-w-0 items-center gap-1 truncate hover:underline"
                                aria-label={copy.sortBy.replace(
                                  '{column}',
                                  column,
                                )}
                              >
                                <span className="truncate">{column}</span>
                                {sort === column
                                  ? direction === 'asc'
                                    ? ' ↑'
                                    : ' ↓'
                                  : ''}
                              </button>
                              {column !== 'id' ? (
                                <button
                                  type="button"
                                  data-reference-popover
                                  className={`rounded p-1 hover:bg-gray-200 ${filters[column] ? 'text-emerald-700' : 'text-gray-500'}`}
                                  aria-label={copy.filterBy.replace(
                                    '{column}',
                                    column,
                                  )}
                                  aria-expanded={openFilter === column}
                                  onClick={() => {
                                    setDraftFilters((current) => ({
                                      ...current,
                                      [column]: filters[column] || '',
                                    }))
                                    setOpenFilter((current) =>
                                      current === column ? null : column,
                                    )
                                  }}
                                >
                                  <Filter className="h-3.5 w-3.5" />
                                </button>
                              ) : null}
                            </div>
                            {column !== 'id' && openFilter === column ? (
                              <div
                                data-reference-popover
                                className="absolute top-full right-1 z-20 mt-1 w-64 rounded-md border bg-white p-3 text-left font-normal shadow-lg"
                              >
                                <label className="text-xs font-medium text-gray-700">
                                  {copy.filterBy.replace('{column}', column)}
                                  <input
                                    autoFocus
                                    className="mt-1 block w-full rounded border px-2 py-1.5 text-sm"
                                    value={draftFilters[column] || ''}
                                    onChange={(event) =>
                                      setDraftFilters((current) => ({
                                        ...current,
                                        [column]: event.target.value,
                                      }))
                                    }
                                    onKeyDown={(event) => {
                                      if (event.key === 'Enter')
                                        applyFilter(column)
                                      if (event.key === 'Escape')
                                        setOpenFilter(null)
                                    }}
                                  />
                                </label>
                                <div className="mt-2 flex justify-end gap-2">
                                  <button
                                    type="button"
                                    className="rounded border px-2 py-1 text-xs"
                                    onClick={() => clearFilter(column)}
                                  >
                                    {copy.clearFilter}
                                  </button>
                                  <button
                                    type="button"
                                    className="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white"
                                    onClick={() => applyFilter(column)}
                                  >
                                    {copy.applyFilter}
                                  </button>
                                </div>
                              </div>
                            ) : null}
                            <button
                              type="button"
                              aria-label={`${copy.resizeColumn} ${column}`}
                              className={`absolute top-0 right-0 z-10 h-full w-2 cursor-col-resize touch-none hover:bg-emerald-500 ${resizingColumn === column ? 'bg-emerald-600' : ''}`}
                              onPointerDown={(event) =>
                                beginResize(column, event)
                              }
                              onPointerMove={(event) =>
                                resizeColumn(event.nativeEvent)
                              }
                              onPointerUp={endResize}
                              onPointerCancel={endResize}
                            />
                          </th>
                        ))}
                        <th aria-hidden="true" className="w-12" />
                        <th className="relative w-12 px-3 py-2 text-left">
                          <button
                            type="button"
                            data-reference-popover
                            onClick={openColumns}
                            className="inline-flex h-6 w-6 items-center justify-center rounded border text-base leading-none hover:bg-gray-200"
                            aria-label={copy.columns || 'Add or remove columns'}
                          >
                            +
                          </button>
                          {columnsOpen ? (
                            <div
                              role="dialog"
                              data-reference-popover
                              aria-labelledby="columns-panel-title"
                              className="absolute top-full right-0 z-20 max-h-[min(40rem,calc(100vh-2rem))] w-[min(28rem,calc(100vw-2rem))] overflow-y-auto rounded-md border bg-white p-4 text-left font-normal shadow-lg"
                            >
                              <div className="mb-3">
                                <h2
                                  id="columns-panel-title"
                                  className="text-lg leading-none font-semibold"
                                >
                                  {copy.columnsTitle}
                                </h2>
                                <p className="text-muted-foreground mt-2 text-sm">
                                  {copy.columnsDescription}
                                </p>
                              </div>
                              <div className="space-y-2">
                                {(
                                  workspace.available_columns ||
                                  workspace.columns ||
                                  []
                                ).map((column) => (
                                  <div
                                    key={column}
                                    className="flex items-center gap-2 text-sm"
                                  >
                                    <label className="flex items-center gap-2">
                                      <Checkbox
                                        checked={draftColumns.includes(column)}
                                        disabled={column === 'id'}
                                        onCheckedChange={() =>
                                          toggleColumn(column)
                                        }
                                      />
                                      {column}
                                    </label>
                                    {draftColumns.includes(column) &&
                                    column !== 'id' ? (
                                      <span className="ml-auto flex gap-1">
                                        <button
                                          type="button"
                                          onClick={() => moveColumn(column, -1)}
                                          disabled={
                                            draftColumns.indexOf(column) <= 1
                                          }
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
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {workspace.citations.map((citation, index) => (
                        <tr
                          key={String(citation.id || index)}
                          className="border-t"
                        >
                          <td className="px-3 py-2 text-right text-gray-500">
                            {index + 1}
                          </td>
                          <td className="px-3 py-2">
                            <Checkbox
                              aria-label={copy.selectCitation.replace(
                                '{id}',
                                String(citation.id),
                              )}
                              checked={selectedIds.includes(
                                Number(citation.id),
                              )}
                              onCheckedChange={() =>
                                toggleSelected(Number(citation.id))
                              }
                            />
                          </td>
                          <td
                            className={`px-4 py-2 text-center ${citation.duplicate_status === 'exact' ? 'bg-red-50 text-red-700' : citation.duplicate_status === 'possible' ? 'bg-amber-50 text-amber-700' : reviews.find((review) => review.group_id === citation.duplicate_group_id)?.decision === 'not_duplicate' ? 'bg-green-50 text-green-700' : 'text-gray-300'}`}
                            title={
                              citation.duplicate_status === 'exact'
                                ? copy.exactDuplicateMatch
                                : citation.duplicate_status === 'possible'
                                  ? copy.possibleDuplicateMatch
                                  : reviews.find(
                                        (review) =>
                                          review.group_id ===
                                          citation.duplicate_group_id,
                                      )?.decision === 'not_duplicate'
                                    ? copy.keptBothReviewGroup
                                    : copy.noDuplicateMatch
                            }
                          >
                            {reviews.find(
                              (review) =>
                                review.group_id === citation.duplicate_group_id,
                            )?.decision === 'not_duplicate' ? (
                              <button
                                type="button"
                                className="mx-auto rounded-sm text-green-700 focus:ring-2 focus:ring-green-600 focus:outline-none"
                                aria-label={copy.openDuplicateReview.replace(
                                  '{id}',
                                  String(citation.id),
                                )}
                                title={copy.reviewKeptBothGroup}
                                onClick={() =>
                                  openDuplicateGroup(
                                    citation.duplicate_group_id,
                                  )
                                }
                              >
                                <CheckCircle
                                  className="h-4 w-4"
                                  aria-hidden="true"
                                />
                              </button>
                            ) : citation.duplicate_status === 'exact' ? (
                              <button
                                type="button"
                                className="mx-auto rounded-sm focus:ring-2 focus:ring-red-600 focus:outline-none"
                                aria-label={copy.openDuplicateReview.replace(
                                  '{id}',
                                  String(citation.id),
                                )}
                                title={copy.openDuplicateGroupReview}
                                onClick={() =>
                                  openDuplicateGroup(
                                    citation.duplicate_group_id,
                                  )
                                }
                              >
                                <CircleX
                                  className="h-4 w-4"
                                  aria-hidden="true"
                                />
                              </button>
                            ) : citation.duplicate_status === 'possible' ? (
                              <button
                                type="button"
                                className="mx-auto rounded-sm focus:ring-2 focus:ring-amber-600 focus:outline-none"
                                aria-label={copy.openDuplicateReview.replace(
                                  '{id}',
                                  String(citation.id),
                                )}
                                title={copy.openDuplicateGroupReview}
                                onClick={() =>
                                  openDuplicateGroup(
                                    citation.duplicate_group_id,
                                  )
                                }
                              >
                                <AlertCircle
                                  className="h-4 w-4"
                                  aria-hidden="true"
                                />
                              </button>
                            ) : (
                              <span aria-label={copy.noDuplicateMatch}>—</span>
                            )}
                          </td>
                          {workspace.columns.map((column) => (
                            <td
                              key={column}
                              className="max-w-md truncate px-3 py-2"
                            >
                              {String(citation[column] ?? '')}
                            </td>
                          ))}
                          <td aria-hidden="true" />
                        </tr>
                      ))}
                      {Array.from({
                        length: workspace.citations.length === 0 ? 15 : 1,
                      }).map((_, index) => (
                        <tr
                          key={`empty-row-${index}`}
                          className="border-t"
                          aria-label={copy.row.replace(
                            '{number}',
                            String(workspace.total_count + index + 1),
                          )}
                        >
                          <td className="px-3 py-2 text-right text-gray-500">
                            {workspace.citations.length > 0 ? (
                              workspace.total_count + index + 1
                            ) : (
                              <span aria-hidden="true" className="block h-5" />
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <span aria-hidden="true" className="block h-5" />
                          </td>
                          <td className="px-2 py-2">
                            <span aria-hidden="true" className="block h-5" />
                          </td>
                          {workspace.columns.map((column) => (
                            <td key={column} className="px-3 py-2">
                              <span aria-hidden="true" className="block h-5" />
                            </td>
                          ))}
                          <td aria-hidden="true" className="py-2">
                            <span aria-hidden="true" className="block h-5" />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : null}
            {workspace ? (
              <div className="text-sm">
                <span>
                  {copy.results.replace(
                    '{count}',
                    String(workspace.total_count),
                  )}
                </span>
              </div>
            ) : null}
          </div>
        )}
      </section>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) void close()
          else setOpen(true)
        }}
      >
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {copy.addReferencesTitle || copy.dialogTitle}
            </DialogTitle>
            <DialogDescription>{copy.dialogDescription}</DialogDescription>
          </DialogHeader>
          <Tabs defaultValue="upload">
            <TabsList className="w-full">
              <TabsTrigger value="upload">
                {copy.uploadTab || 'Upload file'}
              </TabsTrigger>
              <TabsTrigger value="search">
                {copy.searchTab || 'Search databases'}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="upload" className="space-y-4 pt-3">
              <label className="flex cursor-pointer items-center justify-center rounded-md border-2 border-dashed border-emerald-300 bg-emerald-50 px-4 py-6 text-center text-sm font-medium text-emerald-900 hover:bg-emerald-100">
                <span>{file ? copy.changeFile : copy.chooseFile}</span>
                <input
                  className="sr-only"
                  type="file"
                  accept=".csv,.ris,.txt,text/csv,text/plain,application/x-research-info-systems"
                  aria-label={copy.file}
                  onChange={(event) => {
                    const selectedFile = event.target.files?.[0] || null
                    setFile(selectedFile)
                    void parseImportColumns(selectedFile)
                    void checkFileForDuplicates(selectedFile)
                  }}
                />
              </label>
              {file ? (
                <div className="flex items-center justify-between rounded-md border bg-gray-50 px-3 py-2 text-sm">
                  <span className="truncate">
                    <strong>{copy.selectedFile}</strong> {file.name} (
                    {Math.ceil(file.size / 1024)} KB)
                  </span>
                  <button
                    type="button"
                    className="ml-3 text-xs font-medium text-gray-600 underline"
                    onClick={() => {
                      setFile(null)
                      setImportColumns([])
                      setSelectedImportColumns([])
                      setTitleImportColumn('')
                      setAbstractImportColumn('')
                    }}
                  >
                    {copy.removeFile}
                  </button>
                </div>
              ) : null}
              {file && importColumns.length ? (
                <div className="space-y-3 rounded-md border p-3">
                  <p className="text-sm text-gray-600">
                    Select which source fields contain the title and abstract. The file is not assumed to use either name.
                  </p>
                  <label className="block text-sm font-medium">
                    Title source field
                    <select
                      value={titleImportColumn}
                      onChange={(event) => setTitleImportColumn(event.target.value)}
                      className="mt-1 w-full rounded-md border px-3 py-2"
                    >
                      <option value="">Select a title field</option>
                      {importColumns.map((column) => <option key={`title-${column}`} value={column}>{column}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm font-medium">
                    Abstract source field
                    <select
                      value={abstractImportColumn}
                      onChange={(event) => setAbstractImportColumn(event.target.value)}
                      className="mt-1 w-full rounded-md border px-3 py-2"
                    >
                      <option value="">Select an abstract field</option>
                      {importColumns.map((column) => <option key={`abstract-${column}`} value={column}>{column}</option>)}
                    </select>
                  </label>
                </div>
              ) : null}
              {file && importColumns.length ? (
                <fieldset className="max-h-48 space-y-2 overflow-y-auto rounded-md border p-3">
                  <legend className="px-1 text-sm font-semibold">
                    {copy.selectDeduplicationColumns ||
                      'Select deduplication columns'}
                  </legend>
                  <label className="flex items-center gap-2 border-b pb-2 text-sm font-medium">
                    <Checkbox
                      checked={
                        selectedImportColumns.length === importColumns.length
                      }
                      onCheckedChange={(checked) =>
                        setSelectedImportColumns(
                          checked === true ? importColumns : [],
                        )
                      }
                      aria-label={
                        copy.selectAllDeduplicationColumns ||
                        'Select All Columns'
                      }
                    />
                    {copy.selectAllDeduplicationColumns || 'Select All Columns'}
                  </label>
                  {importColumns.map((column) => (
                    <label
                      key={column}
                      className="flex items-center gap-2 text-sm"
                    >
                      <Checkbox
                        checked={selectedImportColumns.includes(column)}
                        onCheckedChange={(checked) =>
                          setSelectedImportColumns((current) =>
                            checked === true
                              ? [...new Set([...current, column])]
                              : current.filter((value) => value !== column),
                          )
                        }
                      />
                      {column}
                    </label>
                  ))}
                </fieldset>
              ) : null}
              {warnings.length ? (
                <ul className="list-disc space-y-1 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                  {warnings.map((warning) => (
                    <li key={warning}>
                      {warning.replace('__duplicate_warning__', '')}
                    </li>
                  ))}
                  {hasDuplicates ? (
                    <li className="list-none pt-2">
                      <label className="flex items-center gap-2">
                        <Checkbox
                          checked={includeDuplicates}
                          onCheckedChange={(checked) =>
                            setIncludeDuplicates(checked === true)
                          }
                        />
                        <span>{copy.includeDuplicates}</span>
                      </label>
                    </li>
                  ) : null}
                </ul>
              ) : null}
              {message ? (
                <p role="status" className="text-sm text-red-700">
                  {message}
                </p>
              ) : null}
            </TabsContent>
            <TabsContent value="search" className="space-y-3 pt-3">
              <p className="rounded-md bg-gray-50 p-3 text-sm text-gray-600">
                {copy.searchDescription}
              </p>
              <form
                className="space-y-3"
                onSubmit={(event) => {
                  event.preventDefault()
                  void searchDatabases()
                }}
              >
                {['Pubmed', 'Scopus', 'EuropePMC'].map((database) => (
                  <label
                    key={database}
                    className="flex items-center gap-3 rounded-md border p-3"
                  >
                    <input
                      type="radio"
                      name="database"
                      value={database}
                      checked={selectedDatabase === database}
                      onChange={() => setSelectedDatabase(database)}
                      className="h-4 w-4"
                    />
                    <span className="w-24 font-medium text-gray-800">
                      {database}
                    </span>
                    <input
                      type="text"
                      aria-label={`${database} ${copy.searchString}`}
                      placeholder={copy.searchString}
                      value={searchStrings[database] || ''}
                      onChange={(event) =>
                        setSearchStrings((current) => ({
                          ...current,
                          [database]: event.target.value,
                        }))
                      }
                      className="min-w-0 flex-1 rounded-md border px-2 py-1 text-sm"
                    />
                  </label>
                ))}
                <button
                  type="submit"
                  disabled={!selectedDatabase || busy}
                  className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
                >
                  {busy ? copy.working : copy.beginSearch}
                </button>
              </form>
              {message ? (
                <p role="status" className="text-sm text-gray-700">
                  {message}
                </p>
              ) : null}
            </TabsContent>
          </Tabs>
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
              {busy ? copy.working : copy.import}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
