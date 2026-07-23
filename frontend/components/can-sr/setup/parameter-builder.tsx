'use client'

import type { Dispatch } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import type { CriteriaDraftAction, CriteriaDraftState, Parameter, ParameterOption, ScreeningQuestion } from './criteria-types'
import type { CriteriaDiagnostic } from './criteria-validation'

type TriggerSource = { stage: 'l1' | 'l2' | 'parameters'; id: string; label: string; options: ParameterOption[] }

const questionSource = (stage: 'l1' | 'l2', question: ScreeningQuestion): TriggerSource => ({
  stage, id: question.id, label: question.question,
  options: question.answers.map(({ id, label, context }) => ({ id, label, context })),
})

function ParameterCard({ parameter, index, count, sources, dependants, referencedOptionIds, dispatch, labels, diagnostics }: {
  parameter: Parameter
  index: number
  count: number
  sources: TriggerSource[]
  dependants: string[]
  referencedOptionIds: Set<string>
  dispatch: Dispatch<CriteriaDraftAction>
  labels: Record<string, string>
  diagnostics: CriteriaDiagnostic[]
}) {
  const prefix = `parameter-${parameter.id}`
  const typeChangeBlocked = parameter.type === 'selection' && dependants.length > 0
  const update = (field: 'name' | 'description' | 'unit_instructions' | 'calculation', value: string) => dispatch({ type: 'update-parameter', parameterId: parameter.id, field, value })
  return <article id={`criteria-item-${parameter.id}`} className={`rounded-lg border bg-white p-4 ${diagnostics.length ? 'border-red-400' : 'border-gray-200'}`} aria-labelledby={`${prefix}-title`}>
    <div className="flex items-center gap-2">
      <strong id={`${prefix}-title`} className="text-sm text-gray-700">{labels.parameter} {index + 1}</strong>
      <div className="ml-auto flex gap-1">
        <button type="button" aria-label={`${labels.moveUpParameter} ${index + 1}`} disabled={index === 0} onClick={() => dispatch({ type: 'move-parameter', parameterId: parameter.id, direction: -1 })} className="rounded border p-2 disabled:opacity-40"><ArrowUp className="h-4 w-4" /></button>
        <button type="button" aria-label={`${labels.moveDownParameter} ${index + 1}`} disabled={index === count - 1} onClick={() => dispatch({ type: 'move-parameter', parameterId: parameter.id, direction: 1 })} className="rounded border p-2 disabled:opacity-40"><ArrowDown className="h-4 w-4" /></button>
        <button type="button" aria-label={`${labels.deleteParameter} ${index + 1}`} onClick={() => {
          if (!dependants.length || window.confirm(labels.deleteDependencyWarning)) dispatch({ type: 'delete-parameter', parameterId: parameter.id })
        }} className="rounded border border-red-200 p-2 text-red-700"><Trash2 className="h-4 w-4" /></button>
      </div>
    </div>
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <div><label className="block text-sm font-medium" htmlFor={`${prefix}-name`}>{labels.parameterName}</label><input id={`${prefix}-name`} value={parameter.name} onChange={(event) => update('name', event.target.value)} className="mt-1 w-full rounded-md border px-3 py-2" /></div>
      <div><label className="block text-sm font-medium" htmlFor={`${prefix}-type`}>{labels.parameterType}</label><select id={`${prefix}-type`} value={parameter.type} onChange={(event) => dispatch({ type: 'set-parameter-type', parameterId: parameter.id, value: event.target.value as 'text' | 'selection' })} className="mt-1 w-full rounded-md border px-3 py-2"><option value="text" disabled={typeChangeBlocked}>{labels.freeText}</option><option value="selection">{labels.selectionList}</option></select></div>
    </div>
    {typeChangeBlocked ? <p role="alert" className="mt-2 rounded bg-amber-50 p-2 text-sm text-amber-900">{labels.typeChangeBlocked}: {dependants.join(', ')}</p> : null}
    <label className="mt-3 block text-sm font-medium" htmlFor={`${prefix}-description`}>{labels.parameterDescription}</label><textarea id={`${prefix}-description`} value={parameter.description} onChange={(event) => update('description', event.target.value)} className="mt-1 min-h-20 w-full rounded-md border px-3 py-2" />
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <div><label className="block text-sm font-medium" htmlFor={`${prefix}-units`}>{labels.unitInstructions}</label><textarea id={`${prefix}-units`} value={parameter.unit_instructions || ''} onChange={(event) => update('unit_instructions', event.target.value)} className="mt-1 min-h-20 w-full rounded-md border px-3 py-2" /></div>
      <div><label className="block text-sm font-medium" htmlFor={`${prefix}-calculation`}>{labels.calculation}</label><textarea id={`${prefix}-calculation`} value={parameter.calculation || ''} onChange={(event) => update('calculation', event.target.value)} className="mt-1 min-h-20 w-full rounded-md border px-3 py-2" /></div>
    </div>
    {parameter.type === 'selection' ? <fieldset className="mt-4 space-y-3">
      <legend className="text-sm font-semibold">{labels.selectionOptions}</legend>
      <label className="block text-sm font-medium" htmlFor={`${prefix}-mode`}>{labels.selectionMode}</label><select id={`${prefix}-mode`} value={parameter.selection_mode} onChange={(event) => dispatch({ type: 'set-selection-mode', parameterId: parameter.id, value: event.target.value as 'single' | 'multiple' })} className="w-full rounded-md border px-3 py-2 md:w-64"><option value="single">{labels.singleSelection}</option><option value="multiple">{labels.multipleSelection}</option></select>
      {parameter.options.map((option, optionIndex) => <div key={option.id} className="grid gap-2 rounded-md bg-gray-50 p-3 md:grid-cols-[1fr_1fr_auto]">
        <div><label className="block text-xs font-medium" htmlFor={`${prefix}-${option.id}-label`}>{labels.optionLabel} {optionIndex + 1}</label><input id={`${prefix}-${option.id}-label`} value={option.label} onChange={(event) => dispatch({ type: 'update-option', parameterId: parameter.id, optionId: option.id, field: 'label', value: event.target.value })} className="mt-1 w-full rounded border px-2 py-1.5" /></div>
        <div><label className="block text-xs font-medium" htmlFor={`${prefix}-${option.id}-context`}>{labels.optionContext}</label><input id={`${prefix}-${option.id}-context`} value={option.context || ''} onChange={(event) => dispatch({ type: 'update-option', parameterId: parameter.id, optionId: option.id, field: 'context', value: event.target.value })} className="mt-1 w-full rounded border px-2 py-1.5" /></div>
        <button type="button" aria-label={`${labels.deleteOption} ${optionIndex + 1}`} disabled={parameter.options.length <= 1} onClick={() => {
          if (!referencedOptionIds.has(option.id) || window.confirm(labels.deleteDependencyWarning)) dispatch({ type: 'delete-option', parameterId: parameter.id, optionId: option.id })
        }} className="self-end rounded border border-red-200 p-2 text-red-700 disabled:opacity-40"><Trash2 className="h-4 w-4" /></button>
      </div>)}
      <button type="button" onClick={() => dispatch({ type: 'add-option', parameterId: parameter.id })} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm"><Plus className="h-4 w-4" />{labels.addOption}</button>
    </fieldset> : null}
    <fieldset className="mt-5 space-y-3 border-t pt-4">
      <legend className="text-sm font-semibold">{labels.triggers}</legend><p className="text-xs text-gray-600">{labels.triggerDescription}</p>
      {parameter.trigger.all.length === 0 ? <p className="text-sm text-gray-500">{labels.alwaysShown}</p> : null}
      {parameter.trigger.all.map((condition, conditionIndex) => {
        const source = sources.find((item) => item.id === condition.source_item_id)
        const answerExists = source?.options.some((option) => option.id === condition.option_id)
        const invalid = !source || !answerExists
        return <div key={`${condition.source_item_id}-${conditionIndex}`} className={`grid gap-2 rounded-md p-3 md:grid-cols-[1fr_1fr_auto] ${invalid ? 'border border-red-300 bg-red-50' : 'bg-gray-50'}`}>
          <div><label className="block text-xs font-medium" htmlFor={`${prefix}-trigger-${conditionIndex}-source`}>{labels.triggerSource}</label><select id={`${prefix}-trigger-${conditionIndex}-source`} value={source ? condition.source_item_id : ''} aria-invalid={invalid} onChange={(event) => { const next = sources.find((item) => item.id === event.target.value); const option = next?.options[0]; if (next && option) dispatch({ type: 'update-parameter-trigger', parameterId: parameter.id, index: conditionIndex, sourceItemId: next.id, optionId: option.id }) }} className="mt-1 w-full rounded border px-2 py-1.5">{!source ? <option value="">{labels.invalidReference}</option> : null}{(['l1', 'l2', 'parameters'] as const).map((group) => <optgroup key={group} label={group === 'l1' ? labels.l1 : group === 'l2' ? labels.l2 : labels.parameters}>{sources.filter((item) => item.stage === group).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</optgroup>)}</select></div>
          <div><label className="block text-xs font-medium" htmlFor={`${prefix}-trigger-${conditionIndex}-answer`}>{labels.triggerAnswer}</label><select id={`${prefix}-trigger-${conditionIndex}-answer`} value={answerExists ? condition.option_id : ''} disabled={!source} aria-invalid={invalid} onChange={(event) => dispatch({ type: 'update-parameter-trigger', parameterId: parameter.id, index: conditionIndex, sourceItemId: condition.source_item_id, optionId: event.target.value })} className="mt-1 w-full rounded border px-2 py-1.5">{!answerExists ? <option value="">{labels.invalidReference}</option> : null}{source?.options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></div>
          <button type="button" aria-label={`${labels.removeTrigger} ${conditionIndex + 1}`} onClick={() => dispatch({ type: 'delete-parameter-trigger', parameterId: parameter.id, index: conditionIndex })} className="self-end rounded border border-red-200 p-2 text-red-700"><Trash2 className="h-4 w-4" /></button>
          {invalid ? <p role="alert" className="text-xs text-red-700 md:col-span-3">{source ? labels.missingAnswerError : labels.triggerOrderError}</p> : null}
        </div>
      })}
      <button type="button" disabled={sources.length === 0} onClick={() => { const source = sources[0]; const option = source?.options[0]; if (source && option) dispatch({ type: 'add-parameter-trigger', parameterId: parameter.id, sourceItemId: source.id, optionId: option.id }) }} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-40"><Plus className="h-4 w-4" />{labels.addTrigger}</button>
    </fieldset>
    {diagnostics.length ? <ul className="mt-3 list-disc rounded bg-red-50 p-3 pl-8 text-sm text-red-800">{diagnostics.map((item) => <li key={`${item.path}-${item.message}`}>{item.message}</li>)}</ul> : null}
  </article>
}

export default function ParameterBuilder({ state, dispatch, labels, diagnostics = [] }: { state: CriteriaDraftState; dispatch: Dispatch<CriteriaDraftAction>; labels: Record<string, string>; diagnostics?: CriteriaDiagnostic[] }) {
  const screeningSources = [...state.criteria.l1.map((item) => questionSource('l1', item)), ...state.criteria.l2.map((item) => questionSource('l2', item))]
  const itemLabels = new Map([...state.criteria.l1.map((item) => [item.id, item.question] as const), ...state.criteria.l2.map((item) => [item.id, item.question] as const), ...state.criteria.parameters.map((item) => [item.id, item.name] as const)])
  const allConditions = state.criteria.parameters.flatMap((item) => item.trigger.all)
  return <section className="space-y-3" aria-labelledby="parameters-heading">
    <div className="flex items-center justify-between"><h4 id="parameters-heading" className="font-semibold">{labels.parameters}</h4><button type="button" onClick={() => dispatch({ type: 'add-parameter' })} className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white"><Plus className="h-4 w-4" />{labels.addParameter}</button></div>
    {state.criteria.parameters.length === 0 ? <p className="rounded-md border border-dashed p-4 text-sm text-gray-500">{labels.noParameters}</p> : null}
    {state.criteria.parameters.map((parameter, index) => {
      const earlierParameters: TriggerSource[] = state.criteria.parameters.slice(0, index).filter((item) => item.type === 'selection').map((item) => ({ stage: 'parameters', id: item.id, label: item.name, options: item.options }))
      const dependants = state.criteria.parameters.filter((item) => item.id !== parameter.id && item.trigger.all.some((condition) => condition.source_item_id === parameter.id)).map((item) => itemLabels.get(item.id) || item.id)
      return <ParameterCard key={parameter.id} parameter={parameter} index={index} count={state.criteria.parameters.length} sources={[...screeningSources, ...earlierParameters]} dependants={dependants} referencedOptionIds={new Set(allConditions.filter((condition) => condition.source_item_id === parameter.id).map((condition) => condition.option_id))} dispatch={dispatch} labels={labels} diagnostics={diagnostics.filter((item) => item.itemId === parameter.id)} />
    })}
  </section>
}
