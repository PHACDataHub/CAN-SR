import { ArrowDown, ArrowUp, ChevronDown, ChevronUp, Plus, X } from 'lucide-react'
import { useState, type Dispatch } from 'react'
import type { CriteriaDraftAction, CriteriaDraftState } from './criteria-types'

export type CitationFieldContract = {
  fields: Array<{ name: string; data_type: string }>
  unavailable_configured_fields: string[]
}

type Row = { kind: 'title' | 'abstract' | 'additional'; column: string | null; index?: number }

export default function CitationFieldSelector({ state, dispatch, contract, labels }: {
  state: CriteriaDraftState
  dispatch: Dispatch<CriteriaDraftAction>
  contract: CitationFieldContract
  labels: Record<string, string>
}) {
  const [collapsed, setCollapsed] = useState(false)
  const available = new Set(contract.fields.map((field) => field.name))
  const title = state.criteria.citation_fields.title || null
  const abstract = state.criteria.citation_fields.abstract || null
  const additional = state.criteria.citation_fields.l1_include
  const rows: Row[] = [
    { kind: 'title', column: title },
    { kind: 'abstract', column: abstract },
    ...additional.map((column, index) => ({ kind: 'additional' as const, column, index })),
  ]
  const selected = new Set([title, abstract, ...additional].filter(Boolean) as string[])
  const options = (current: string | null) => [
    ...(current && !available.has(current) ? [{ name: current, unavailable: true }] : []),
    ...contract.fields.filter((field) => !selected.has(field.name) || field.name === current).map((field) => ({ name: field.name, unavailable: false })),
  ]
  const setColumn = (row: Row, value: string | null) => {
    if (row.kind === 'title') dispatch({ type: 'set-title-field', value })
    else if (row.kind === 'abstract') dispatch({ type: 'set-abstract-field', value })
    else if (row.index !== undefined) dispatch({ type: 'set-citation-fields', value: additional.map((item, index) => index === row.index ? value || '' : item).filter(Boolean) })
  }
  const move = (index: number, offset: number) => {
    const target = index + offset
    if (target < 0 || target >= additional.length) return
    const next = [...additional]
    ;[next[index], next[target]] = [next[target], next[index]]
    dispatch({ type: 'set-citation-fields', value: next })
  }
  const labelFor = (kind: Row['kind']) => kind === 'title' ? labels.titleField : kind === 'abstract' ? labels.abstractField : labels.additionalField
  const statusFor = (row: Row) => !row.column ? labels.requiredField : available.has(row.column) ? labels.available : labels.unavailableField

  return <section id="criteria-l1-fields" tabIndex={-1} className="space-y-3" aria-labelledby="citation-fields-heading">
    <div className="flex items-center gap-2 rounded-md bg-gray-50 p-2">
      <button type="button" aria-expanded={!collapsed} aria-controls="citation-fields-body" aria-label={`${collapsed ? labels.expand : labels.collapse} ${labels.citationFields}`} title={collapsed ? labels.expand : labels.collapse} onClick={() => setCollapsed((value) => !value)} className="rounded p-1 text-gray-600 hover:bg-gray-200">
        {collapsed ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
      </button>
      <h4 id="citation-fields-heading" className="font-semibold">{labels.citationFields}</h4>
      {!collapsed && <button type="button" aria-label={labels.addAdditionalField} disabled={options(null).length === 0} onClick={() => dispatch({ type: 'set-citation-fields', value: [...additional, options(null)[0]?.name || ''] })} className="ml-auto inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"><Plus className="h-4 w-4" />{labels.addAdditionalField}</button>}
    </div>
    {!collapsed ? <div id="citation-fields-body">
      <p className="text-sm text-gray-600">{labels.titleAbstractFieldsDescription}</p>
      <div className="mt-4 overflow-x-auto rounded-md border">
        <table className="w-full text-left text-sm">
          <thead className="bg-gray-50"><tr><th scope="col" className="px-3 py-2 font-medium">{labels.field}</th><th scope="col" className="px-3 py-2 font-medium">{labels.selection}</th><th scope="col" className="px-3 py-2 font-medium">{labels.status}</th><th scope="col" className="px-3 py-2 text-right font-medium">{labels.actions}</th></tr></thead>
          <tbody className="divide-y">
            {rows.map((row) => <tr key={`${row.kind}-${row.index ?? 0}`} className={!row.column || !available.has(row.column) ? 'bg-amber-50' : ''}>
              <td className="px-3 py-2 font-medium">{labelFor(row.kind)}{row.kind !== 'additional' && <span className="ml-2 text-xs font-normal text-gray-500">{labels.required}</span>}</td>
              <td className="px-3 py-2"><select aria-label={`${labelFor(row.kind)} ${labels.selection}`} value={row.column || ''} onChange={(event) => setColumn(row, event.target.value || null)} className="w-full rounded-md border px-2 py-1"><option value="">{labels.selectColumn}</option>{options(row.column).map((option) => <option key={option.name} value={option.name}>{option.name}{option.unavailable ? ` · ${labels.unavailableField}` : ''}</option>)}</select></td>
              <td className="px-3 py-2">{!row.column ? <span className="text-amber-800">{statusFor(row)}</span> : available.has(row.column) ? labels.available : <span className="text-amber-800">{labels.unavailableField}</span>}</td>
              <td className="px-3 py-2"><div className="flex justify-end gap-2">{row.kind === 'additional' && row.index !== undefined && <><button type="button" disabled={row.index === 0} aria-label={`${labels.moveUp} ${row.column || labels.additionalField}`} onClick={() => move(row.index!, -1)} className="rounded border p-1 disabled:opacity-40"><ArrowUp className="h-4 w-4" /></button><button type="button" disabled={row.index === additional.length - 1} aria-label={`${labels.moveDown} ${row.column || labels.additionalField}`} onClick={() => move(row.index!, 1)} className="rounded border p-1 disabled:opacity-40"><ArrowDown className="h-4 w-4" /></button><button type="button" aria-label={`${labels.removeField} ${row.column || labels.additionalField}`} onClick={() => dispatch({ type: 'set-citation-fields', value: additional.filter((_item, index) => index !== row.index) })} className="rounded border border-red-200 p-1 text-red-700"><X className="h-4 w-4" /></button></>}</div></td>
            </tr>)}
          </tbody>
        </table>
      </div>
      <label className="mt-4 block text-sm font-medium" htmlFor="criteria-doi-field">{labels.doiField}</label>
      <select id="criteria-doi-field" value={state.criteria.citation_fields.doi || ''} onChange={(event) => dispatch({ type: 'set-doi', value: event.target.value || null })} className="mt-1 w-full rounded-md border px-3 py-2"><option value="">{labels.noDoiField}</option>{state.criteria.citation_fields.doi && !available.has(state.criteria.citation_fields.doi) ? <option value={state.criteria.citation_fields.doi}>{state.criteria.citation_fields.doi} · {labels.unavailableField}</option> : null}{contract.fields.map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}</select>
    </div> : null}
  </section>
}
