'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, Loader2, RefreshCw } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  CitationExportSchema, downloadCitationExport, loadCitationExportSchema,
} from '@/hooks/use-citation-export'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

type Selection = Record<string, { items: Set<string>; dimensions: Set<string> }>
type ExportGroup = CitationExportSchema['groups'][number]
type Props = {
  srId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  currentViewIds?: number[]
  trigger?: React.ReactNode
}

export function CitationExportDialog({ srId, open, onOpenChange, currentViewIds }: Props) {
  const dict = useDictionary() as any
  const copy = dict.citationExport
  const [schema, setSchema] = useState<CitationExportSchema | null>(null)
  const [selection, setSelection] = useState<Selection>({})
  const [scope, setScope] = useState('all')
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError(''); setSchema(null)
    try {
      const next = await loadCitationExportSchema(srId)
      const defaults: Selection = {}
      next.groups.forEach((group) => {
        defaults[group.id] = {
          items: new Set(group.items.filter((item) => item.default_selected).map((item) => item.id)),
          dimensions: new Set(group.dimensions.filter((dimension) => dimension.default_selected).map((dimension) => dimension.id)),
        }
      })
      setSchema(next); setSelection(defaults); setScope('all')
    } catch (cause: any) { setError(cause?.message || copy.loadError) }
    finally { setLoading(false) }
  }, [srId, copy.loadError])

  useEffect(() => { if (open) void load() }, [open, load])

  const selectableItemIds = (group: ExportGroup) => group.items
    .filter((item) => group.id === 'citation' || !!item.available_dimensions?.length)
    .map((item) => item.id)

  const updateSet = (groupId: string, key: 'items' | 'dimensions', id: string, checked: boolean) => {
    setSelection((previous) => {
      const group = previous[groupId] || { items: new Set<string>(), dimensions: new Set<string>() }
      const next = new Set(group[key])
      if (checked) next.add(id)
      else next.delete(id)
      if (key === 'dimensions') {
        const schemaGroup = schema?.groups.find((candidate) => candidate.id === groupId)
        const selectable = new Set(schemaGroup?.items
          .filter((item) => [...next].some((dimension) => item.available_dimensions?.includes(dimension)))
          .map((item) => item.id) || [])
        return { ...previous, [groupId]: {
          dimensions: next,
          items: new Set([...group.items].filter((item) => selectable.has(item))),
        } }
      }
      return { ...previous, [groupId]: { ...group, [key]: next } }
    })
  }
  const toggleGroup = (groupId: string, checked: boolean) => {
    const group = schema?.groups.find((candidate) => candidate.id === groupId)
    if (!group) return
    const allDimensions = new Set(group.dimensions.map((dimension) => dimension.id))
    setSelection((previous) => ({ ...previous, [groupId]: {
      items: new Set(checked ? selectableItemIds(group) : []),
      dimensions: checked ? allDimensions : new Set(),
    } }))
  }
  const toggleAll = (checked: boolean) => {
    if (!schema) return
    setSelection(Object.fromEntries(schema.groups.map((group) => [group.id, {
      items: new Set(checked ? selectableItemIds(group) : []),
      dimensions: new Set(checked ? group.dimensions.map((dimension) => dimension.id) : []),
    }])))
  }
  const selectionState = (selectedCount: number, totalCount: number) => (
    selectedCount === 0 ? false : selectedCount === totalCount ? true : 'indeterminate'
  )
  const totalOptions = schema?.groups.reduce(
    (total, group) => total + selectableItemIds(group).length + group.dimensions.length, 0,
  ) || 0
  const checkedOptions = schema?.groups.reduce((total, group) => {
    const selected = selection[group.id]
    return total + (selected?.items.size || 0) + (selected?.dimensions.size || 0)
  }, 0) || 0
  const allState = selectionState(checkedOptions, totalOptions)
  const selectedColumns = useMemo(() => schema?.groups.reduce((total, group) => {
    const selected = selection[group.id]
    if (!selected) return total
    if (group.id === 'citation') return total + selected.items.size
    return total + group.items.reduce((itemTotal, item) => {
      if (!selected.items.has(item.id)) return itemTotal
      const applicable = [...selected.dimensions]
        .filter((dimension) => item.available_dimensions?.includes(dimension))
      if (group.id !== 'parameters') return itemTotal + applicable.length
      return itemTotal + applicable.reduce(
        (dimensionTotal, dimension) => dimensionTotal + (dimension.endsWith('_value') ? 2 : 1), 0,
      )
    }, 0)
  }, 0) || 0, [schema, selection])
  const canUseCurrent = !!currentViewIds?.length && currentViewIds.length <= 500

  const submit = async () => {
    if (!schema || !selectedColumns) return
    setSubmitting(true); setError('')
    try {
      await downloadCitationExport(srId, {
        schema_version: schema.schema_version, format: 'csv',
        row_scope: scope === 'citation_ids'
          ? { kind: scope, citation_ids: currentViewIds }
          : { kind: scope },
        selections: schema.groups.map((group) => ({
          group: group.id,
          items: [...(selection[group.id]?.items || [])],
          dimensions: [...(selection[group.id]?.dimensions || [])],
        })).filter((group) => group.items.length),
      })
      onOpenChange(false)
    } catch (cause: any) { setError(cause?.message || copy.exportError) }
    finally { setSubmitting(false) }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>
        {loading ? <div className="flex items-center gap-2 py-10 text-sm"><Loader2 className="h-4 w-4 animate-spin" />{copy.loading}</div> : null}
        {error ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error} {!schema && <button onClick={() => void load()} className="ml-2 underline"><RefreshCw className="inline h-3 w-3" /> {copy.retry}</button>}</div> : null}
        {schema ? <>
          <label className="flex items-center gap-2 rounded-md border bg-gray-50 p-3 font-semibold">
            <Checkbox aria-label={copy.selectAll} checked={allState}
              onCheckedChange={(value) => toggleAll(value === true)} />
            {copy.selectAll}
          </label>
          <fieldset className="space-y-2 rounded-md border p-3">
            <legend className="px-1 text-sm font-semibold">{copy.rows}</legend>
            {[
              ['all', copy.all], ['l1_included', copy.l1Included], ['l2_included', copy.l2Included],
              ['citation_ids', copy.currentView],
            ].map(([value, label]) => <label key={value} className="flex items-center gap-2 text-sm">
              <input type="radio" name="export-scope" value={value} checked={scope === value}
                disabled={value === 'citation_ids' && !canUseCurrent} onChange={() => setScope(value)} />
              {label}{value === 'citation_ids' && !canUseCurrent ? ` (${copy.unavailable})` : ''}
            </label>)}
          </fieldset>
          <div className="space-y-3">
            {schema.groups.map((group) => {
              const selected = selection[group.id] || { items: new Set(), dimensions: new Set() }
              const descendantCount = selectableItemIds(group).length + group.dimensions.length
              const checkedCount = selected.items.size + selected.dimensions.size
              const state = selectionState(checkedCount, descendantCount)
              return <details key={group.id} open className="rounded-md border p-3">
                <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold">
                  <Checkbox aria-label={`${copy.selectAll} ${group.label}`} checked={state}
                    onCheckedChange={(value) => toggleGroup(group.id, value === true)} onClick={(event) => event.stopPropagation()} />
                  {group.label}
                </summary>
                {group.dimensions.length ? <div className="mt-3 grid gap-2 border-b pb-3 sm:grid-cols-2">
                  {group.dimensions.map((dimension) => <label key={dimension.id} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={selected.dimensions.has(dimension.id)} onCheckedChange={(value) => updateSet(group.id, 'dimensions', dimension.id, value === true)} />{dimension.label}
                  </label>)}
                </div> : null}
                <div className="mt-3 max-h-48 space-y-2 overflow-y-auto pl-1">
                  {group.items.map((item) => <label key={item.id} className="flex items-start gap-2 text-sm">
                    <Checkbox checked={selected.items.has(item.id)}
                      disabled={group.id !== 'citation' && ![...selected.dimensions].some((dimension) => item.available_dimensions?.includes(dimension))}
                      onCheckedChange={(value) => updateSet(group.id, 'items', item.id, value === true)} />
                    <span>{item.category ? <span className="text-gray-500">{item.category}: </span> : null}{item.label}</span>
                  </label>)}
                  {!group.items.length ? <p className="text-sm text-gray-500">{copy.noneAvailable}</p> : null}
                </div>
              </details>
            })}
          </div>
          <p className="text-sm text-gray-600">{copy.selected.replace('{count}', String(selectedColumns))}</p>
        </> : null}
        <DialogFooter>
          <button type="button" onClick={() => onOpenChange(false)} className="rounded-md border px-4 py-2 text-sm">{copy.cancel}</button>
          <button type="button" onClick={() => void submit()} disabled={!schema || !selectedColumns || submitting}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}{submitting ? copy.preparing : copy.exportCsv}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}