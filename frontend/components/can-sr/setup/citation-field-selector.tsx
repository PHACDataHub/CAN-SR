import { ArrowDown, ArrowUp, ChevronDown, ChevronUp, Plus, X } from 'lucide-react'
import { useEffect, useRef, useState, type Dispatch } from 'react'
import type { CriteriaDraftAction, CriteriaDraftState } from './criteria-types'

export type CitationFieldContract = {
  fields: Array<{ name: string; data_type: string }>
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
  const addable = contract.fields.filter((field) => !selected.includes(field.name))
  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const addMenuRef = useRef<HTMLDivElement>(null)
  const setSelected = (value: string[]) => dispatch({ type: 'set-citation-fields', value })
  const move = (index: number, offset: number) => {
    const next = [...selected]
    ;[next[index], next[index + offset]] = [next[index + offset], next[index]]
    setSelected(next)
  }
  useEffect(() => {
    if (!addMenuOpen) return
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!addMenuRef.current?.contains(event.target as Node)) setAddMenuOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAddMenuOpen(false)
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [addMenuOpen])
  return <section id="criteria-l1-fields" tabIndex={-1} className="space-y-3" aria-labelledby="citation-fields-heading">
    <div className="flex items-center gap-2 rounded-md bg-gray-50 p-2">
      <button type="button" aria-expanded={!collapsed} aria-controls="citation-fields-body" aria-label={`${collapsed ? labels.expand : labels.collapse} ${labels.citationFields}`} title={collapsed ? labels.expand : labels.collapse} onClick={() => { setCollapsed((value) => !value); setAddMenuOpen(false) }} className="rounded p-1 text-gray-600 hover:bg-gray-200">
        {collapsed ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
      </button>
      <h4 id="citation-fields-heading" className="font-semibold">{labels.citationFields} <span className="font-normal text-gray-500">({selected.length})</span></h4>
      <div ref={addMenuRef} className="relative ml-auto">
        <button type="button" aria-label={labels.addField} aria-haspopup="menu" aria-expanded={addMenuOpen} aria-controls="title-abstract-field-menu" disabled={addable.length === 0} onClick={() => setAddMenuOpen((open) => !open)} className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40">
          <Plus className="h-4 w-4" />{labels.addField}
        </button>
        {addMenuOpen ? <div id="title-abstract-field-menu" role="menu" className="absolute right-0 z-10 mt-2 min-w-48 overflow-hidden rounded-md border bg-white py-1 shadow-lg">
          {addable.map((field) => <button key={field.name} type="button" role="menuitem" onClick={() => { setSelected([...selected, field.name]); setAddMenuOpen(false) }} className="block w-full px-3 py-2 text-left text-sm hover:bg-gray-100 focus:bg-gray-100">{field.name}</button>)}
        </div> : null}
      </div>
    </div>
    {!collapsed ? <div id="citation-fields-body">
    <p className="text-sm text-gray-600">{labels.titleAbstractFieldsDescription}</p>
    <div className="mt-4 overflow-x-auto rounded-md border">
      <table className="w-full text-left text-sm">
        <thead className="bg-gray-50">
          <tr><th scope="col" className="px-3 py-2 font-medium">{labels.field}</th><th scope="col" className="px-3 py-2 font-medium">{labels.status}</th><th scope="col" className="px-3 py-2 text-right font-medium">{labels.actions}</th></tr>
        </thead>
        <tbody className="divide-y">
          {selected.length === 0 ? <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-600">{labels.noSelectedFields}</td></tr> : selected.map((name, index) => <tr key={name} className={available.has(name) ? '' : 'bg-amber-50'}>
            <td className="px-3 py-2 font-medium">{name}</td>
            <td className="px-3 py-2">{available.has(name) ? labels.available : <span className="text-amber-800">{labels.unavailableField}</span>}</td>
            <td className="px-3 py-2"><div className="flex justify-end gap-2">
              <button type="button" disabled={index === 0} aria-label={`${labels.moveUp} ${name}`} onClick={() => move(index, -1)} className="rounded border p-1 disabled:opacity-40"><ArrowUp className="h-4 w-4" /></button>
              <button type="button" disabled={index === selected.length - 1} aria-label={`${labels.moveDown} ${name}`} onClick={() => move(index, 1)} className="rounded border p-1 disabled:opacity-40"><ArrowDown className="h-4 w-4" /></button>
              <button type="button" aria-label={`${labels.removeField} ${name}`} onClick={() => setSelected(selected.filter((value) => value !== name))} className="rounded border border-red-200 p-1 text-red-700"><X className="h-4 w-4" /></button>
            </div></td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <label className="mt-4 block text-sm font-medium" htmlFor="criteria-doi-field">{labels.doiField}</label>
    <select id="criteria-doi-field" value={state.criteria.citation_fields.doi || ''} onChange={(event) => dispatch({ type: 'set-doi', value: event.target.value || null })} className="mt-1 w-full rounded-md border px-3 py-2">
      <option value="">{labels.noDoiField}</option>
      {state.criteria.citation_fields.doi && !available.has(state.criteria.citation_fields.doi) ? <option value={state.criteria.citation_fields.doi}>{state.criteria.citation_fields.doi} · {labels.unavailableField}</option> : null}
      {contract.fields.map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}
    </select>
    </div> : null}
  </section>
}
