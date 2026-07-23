'use client'

import type { Dispatch } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import type { CriteriaDraftAction, CriteriaDraftState, ScreeningQuestion } from './criteria-types'
import ParameterBuilder from './parameter-builder'
import type { CriteriaDiagnostic } from './criteria-validation'
import CitationFieldSelector, { type CitationFieldContract } from './citation-field-selector'

type SourceOption = { stage: 'l1' | 'l2'; question: ScreeningQuestion }

type Props = {
  state: CriteriaDraftState
  dispatch: Dispatch<CriteriaDraftAction>
  labels: Record<string, string>
  diagnostics?: CriteriaDiagnostic[]
  citationFields?: CitationFieldContract
}

function QuestionCard({
  question,
  index,
  count,
  stage,
  dispatch,
  labels,
  sources,
  diagnostics,
  sourceReferenced,
  referencedAnswerIds,
}: {
  question: ScreeningQuestion
  index: number
  count: number
  stage: 'l1' | 'l2'
  dispatch: Dispatch<CriteriaDraftAction>
  labels: Record<string, string>
  sources: SourceOption[]
  diagnostics: CriteriaDiagnostic[]
  sourceReferenced: boolean
  referencedAnswerIds: Set<string>
}) {
  const prefix = `${stage}-${question.id}`
  return (
    <article id={`criteria-item-${question.id}`} className={`rounded-lg border bg-white p-4 ${diagnostics.length ? 'border-red-400' : 'border-gray-200'}`} aria-labelledby={`${prefix}-title`}>
      <div className="flex items-center gap-2">
        <strong id={`${prefix}-title`} className="text-sm text-gray-700">{labels.question} {index + 1}</strong>
        <div className="ml-auto flex gap-1">
          <button type="button" aria-label={`${labels.moveUp} ${index + 1}`} disabled={index === 0} onClick={() => dispatch({ type: 'move-question', stage, questionId: question.id, direction: -1 })} className="rounded border p-2 disabled:opacity-40"><ArrowUp className="h-4 w-4" /></button>
          <button type="button" aria-label={`${labels.moveDown} ${index + 1}`} disabled={index === count - 1} onClick={() => dispatch({ type: 'move-question', stage, questionId: question.id, direction: 1 })} className="rounded border p-2 disabled:opacity-40"><ArrowDown className="h-4 w-4" /></button>
          <button type="button" aria-label={`${labels.deleteQuestion} ${index + 1}`} onClick={() => {
            if (!sourceReferenced || window.confirm(labels.deleteDependencyWarning)) dispatch({ type: 'delete-question', stage, questionId: question.id })
          }} className="rounded border border-red-200 p-2 text-red-700"><Trash2 className="h-4 w-4" /></button>
        </div>
      </div>
      <label className="mt-3 block text-sm font-medium" htmlFor={`${prefix}-question`}>{labels.questionText}</label>
      <input id={`${prefix}-question`} value={question.question} onChange={(event) => dispatch({ type: 'update-question', stage, questionId: question.id, field: 'question', value: event.target.value })} className="mt-1 w-full rounded-md border px-3 py-2" />
      <label className="mt-3 block text-sm font-medium" htmlFor={`${prefix}-context`}>{labels.context}</label>
      <textarea id={`${prefix}-context`} value={question.context || ''} onChange={(event) => dispatch({ type: 'update-question', stage, questionId: question.id, field: 'context', value: event.target.value })} className="mt-1 min-h-20 w-full rounded-md border px-3 py-2" />
      <fieldset className="mt-4 space-y-3">
        <legend className="text-sm font-semibold">{labels.answers}</legend>
        {question.answers.map((answer, answerIndex) => (
          <div key={answer.id} className="grid gap-2 rounded-md bg-gray-50 p-3 md:grid-cols-[1fr_1fr_auto]">
            <div>
              <label className="block text-xs font-medium" htmlFor={`${prefix}-${answer.id}-label`}>{labels.answerLabel} {answerIndex + 1}</label>
              <input id={`${prefix}-${answer.id}-label`} value={answer.label} onChange={(event) => dispatch({ type: 'update-answer', stage, questionId: question.id, answerId: answer.id, field: 'label', value: event.target.value })} className="mt-1 w-full rounded border px-2 py-1.5" />
            </div>
            <div>
              <label className="block text-xs font-medium" htmlFor={`${prefix}-${answer.id}-decision`}>{labels.decision}</label>
              <select id={`${prefix}-${answer.id}-decision`} value={answer.decision} onChange={(event) => dispatch({ type: 'update-answer', stage, questionId: question.id, answerId: answer.id, field: 'decision', value: event.target.value })} className="mt-1 w-full rounded border px-2 py-1.5">
                <option value="include">{labels.include}</option><option value="exclude">{labels.exclude}</option>
              </select>
            </div>
            <button type="button" aria-label={`${labels.deleteAnswer} ${answerIndex + 1}`} disabled={question.answers.length <= 2} onClick={() => {
              if (!referencedAnswerIds.has(answer.id) || window.confirm(labels.deleteDependencyWarning)) dispatch({ type: 'delete-answer', stage, questionId: question.id, answerId: answer.id })
            }} className="self-end rounded border border-red-200 p-2 text-red-700 disabled:opacity-40"><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
      </fieldset>
      <button type="button" onClick={() => dispatch({ type: 'add-answer', stage, questionId: question.id })} className="mt-3 inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm"><Plus className="h-4 w-4" />{labels.addAnswer}</button>
      <fieldset className="mt-5 space-y-3 border-t pt-4">
        <legend className="text-sm font-semibold">{labels.triggers}</legend>
        <p className="text-xs text-gray-600">{labels.triggerDescription}</p>
        {question.trigger.all.length === 0 ? <p className="text-sm text-gray-500">{labels.alwaysShown}</p> : null}
        {question.trigger.all.map((condition, conditionIndex) => {
          const source = [...sources, { stage, question }].find((item) => item.question.id === condition.source_item_id)
          const sourceIsEarlier = sources.some((item) => item.question.id === condition.source_item_id)
          const answerExists = source?.question.answers.some((answer) => answer.id === condition.option_id)
          const invalid = !sourceIsEarlier || !answerExists
          return <div key={`${condition.source_item_id}-${conditionIndex}`} className={`grid gap-2 rounded-md p-3 md:grid-cols-[1fr_1fr_auto] ${invalid ? 'border border-red-300 bg-red-50' : 'bg-gray-50'}`}>
            <div>
              <label className="block text-xs font-medium" htmlFor={`${prefix}-trigger-${conditionIndex}-source`}>{labels.triggerSource}</label>
              <select id={`${prefix}-trigger-${conditionIndex}-source`} value={sourceIsEarlier ? condition.source_item_id : ''} aria-invalid={invalid} onChange={(event) => {
                const nextSource = sources.find((item) => item.question.id === event.target.value)
                const firstAnswer = nextSource?.question.answers[0]
                if (nextSource && firstAnswer) dispatch({ type: 'update-trigger', stage, questionId: question.id, index: conditionIndex, sourceItemId: nextSource.question.id, optionId: firstAnswer.id })
              }} className="mt-1 w-full rounded border px-2 py-1.5">
                {invalid ? <option value="">{labels.invalidReference}</option> : null}
                {(['l1', 'l2'] as const).map((group) => <optgroup key={group} label={group === 'l1' ? labels.l1 : labels.l2}>{sources.filter((item) => item.stage === group).map((item) => <option key={item.question.id} value={item.question.id}>{item.question.question}</option>)}</optgroup>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium" htmlFor={`${prefix}-trigger-${conditionIndex}-answer`}>{labels.triggerAnswer}</label>
              <select id={`${prefix}-trigger-${conditionIndex}-answer`} value={answerExists ? condition.option_id : ''} aria-invalid={invalid} disabled={!sourceIsEarlier} onChange={(event) => dispatch({ type: 'update-trigger', stage, questionId: question.id, index: conditionIndex, sourceItemId: condition.source_item_id, optionId: event.target.value })} className="mt-1 w-full rounded border px-2 py-1.5">
                {!answerExists ? <option value="">{labels.invalidReference}</option> : null}
                {source?.question.answers.map((answer) => <option key={answer.id} value={answer.id}>{answer.label}</option>)}
              </select>
            </div>
            <button type="button" aria-label={`${labels.removeTrigger} ${conditionIndex + 1}`} onClick={() => dispatch({ type: 'delete-trigger', stage, questionId: question.id, index: conditionIndex })} className="self-end rounded border border-red-200 p-2 text-red-700"><Trash2 className="h-4 w-4" /></button>
            {invalid ? <p role="alert" className="text-xs text-red-700 md:col-span-3">{sourceIsEarlier ? labels.missingAnswerError : labels.triggerOrderError}</p> : null}
          </div>
        })}
        <button type="button" disabled={sources.length === 0} onClick={() => {
          const source = sources[0]
          const answer = source?.question.answers[0]
          if (source && answer) dispatch({ type: 'add-trigger', stage, questionId: question.id, sourceItemId: source.question.id, optionId: answer.id })
        }} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-40"><Plus className="h-4 w-4" />{labels.addTrigger}</button>
      </fieldset>
      {diagnostics.length ? <ul className="mt-3 list-disc rounded bg-red-50 p-3 pl-8 text-sm text-red-800">{diagnostics.map((item) => <li key={`${item.path}-${item.message}`}>{item.message}</li>)}</ul> : null}
    </article>
  )
}

export default function CriteriaBuilder({ state, dispatch, labels, diagnostics = [], citationFields = { fields: [], doi_suggestions: [], unavailable_configured_fields: [] } }: Props) {
  const ordered: SourceOption[] = [
    ...state.criteria.l1.map((question) => ({ stage: 'l1' as const, question })),
    ...state.criteria.l2.map((question) => ({ stage: 'l2' as const, question })),
  ]
  const conditions = [...state.criteria.l1, ...state.criteria.l2, ...state.criteria.parameters].flatMap((item) => item.trigger.all)
  return (
    <div className="space-y-6">
      <CitationFieldSelector state={state} dispatch={dispatch} contract={citationFields} labels={labels} />
      {(['l1', 'l2'] as const).map((stage) => (
        <section key={stage} className="space-y-3" aria-labelledby={`${stage}-heading`}>
          <div className="flex items-center justify-between">
            <h4 id={`${stage}-heading`} className="font-semibold">{stage === 'l1' ? labels.l1 : labels.l2}</h4>
            <button type="button" onClick={() => dispatch({ type: 'add-question', stage })} className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white"><Plus className="h-4 w-4" />{labels.addQuestion}</button>
          </div>
          {state.criteria[stage].length === 0 ? <p className="rounded-md border border-dashed p-4 text-sm text-gray-500">{labels.noQuestions}</p> : null}
          {state.criteria[stage].map((question, index) => {
            const position = ordered.findIndex((item) => item.question.id === question.id)
            return <QuestionCard key={question.id} question={question} index={index} count={state.criteria[stage].length} stage={stage} dispatch={dispatch} labels={labels} sources={ordered.slice(0, position)} diagnostics={diagnostics.filter((item) => item.itemId === question.id)} sourceReferenced={conditions.some((condition) => condition.source_item_id === question.id)} referencedAnswerIds={new Set(conditions.filter((condition) => condition.source_item_id === question.id).map((condition) => condition.option_id))} />
          })}
        </section>
      ))}
      <ParameterBuilder state={state} dispatch={dispatch} labels={labels} diagnostics={diagnostics} />
    </div>
  )
}
