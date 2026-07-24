import { ArrowDown, ArrowUp, X } from 'lucide-react'
import type { Dispatch } from 'react'
import type { CriteriaDraftAction, CriteriaDraftState } from './criteria-types'

export type CitationFieldContract = {
  fields: Array<{ name: string; data_type: string; doi_likelihood: number }>
  doi_suggestions: string[]
  unavailable_configured_fields: string[]
}

export default function CitationFieldSelector({ state, dispatch, contract, labels }: {
  state: CriteriaDraftState
  dispatch: Dispatch<CriteriaDraftAction>
  contract: CitationFieldContract
  labels: Record<string, string>
}) {
  const selected = state.criteria.citation_fields.l1_include
  const available = new Set(contract.fields.map((field) => field.name))
  const setSelected = (value: string[]) => dispatch({ type: 'set-citation-fields', value })
  const move = (index: number, offset: number) => {
    const next = [...selected]
    ;[next[index], next[index + offset]] = [next[index + offset], next[index]]
    setSelected(next)
  }
  return <section id="criteria-l1-fields" tabIndex={-1} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
    <h4 className="font-semibold">{labels.citationFields}</h4>
    {contract.fields.length === 0 ? <p className="mt-2 text-sm text-gray-600">{labels.noCitationFields}</p> : <fieldset className="mt-3">
      <legend className="text-sm font-medium">{labels.availableFields}</legend>
      <div className="mt-2 flex flex-wrap gap-3">{contract.fields.map((field) => <label key={field.name} className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={selected.includes(field.name)} onChange={(event) => setSelected(event.target.checked ? [...selected, field.name] : selected.filter((name) => name !== field.name))} />{field.name}
      </label>)}</div>
    </fieldset>}
    <ol className="mt-4 space-y-2" aria-label={labels.selectedFieldOrder}>{selected.map((name, index) => <li key={name} className={`flex items-center gap-2 rounded border p-2 text-sm ${available.has(name) ? '' : 'border-amber-400 bg-amber-50'}`}>
      <span className="mr-auto">{index + 1}. {name}{!available.has(name) ? ` · ${labels.unavailableField}` : ''}</span>
      <button type="button" disabled={index === 0} aria-label={`${labels.moveUp} ${name}`} onClick={() => move(index, -1)} className="rounded border p-1 disabled:opacity-40"><ArrowUp className="h-4 w-4" /></button>
      <button type="button" disabled={index === selected.length - 1} aria-label={`${labels.moveDown} ${name}`} onClick={() => move(index, 1)} className="rounded border p-1 disabled:opacity-40"><ArrowDown className="h-4 w-4" /></button>
      <button type="button" aria-label={`${labels.removeField} ${name}`} onClick={() => setSelected(selected.filter((value) => value !== name))} className="rounded border border-red-200 p-1 text-red-700"><X className="h-4 w-4" /></button>
    </li>)}</ol>
    <label className="mt-4 block text-sm font-medium" htmlFor="criteria-doi-field">{labels.doiField}</label>
    <select id="criteria-doi-field" value={state.criteria.citation_fields.doi || ''} onChange={(event) => dispatch({ type: 'set-doi', value: event.target.value || null })} className="mt-1 w-full rounded-md border px-3 py-2">
      <option value="">{labels.noDoiField}</option>
      {state.criteria.citation_fields.doi && !available.has(state.criteria.citation_fields.doi) ? <option value={state.criteria.citation_fields.doi}>{state.criteria.citation_fields.doi} · {labels.unavailableField}</option> : null}
      {contract.fields.map((field) => <option key={field.name} value={field.name}>{field.name}{contract.doi_suggestions.includes(field.name) ? ` · ${labels.likelyDoi}` : ''}</option>)}
    </select>
  </section>
}
