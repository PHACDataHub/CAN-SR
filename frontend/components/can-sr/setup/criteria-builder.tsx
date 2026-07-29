'use client'

import { useEffect, useRef, useState, type Dispatch } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, ChevronUp, ChevronsDown, Pencil, Plus, Trash2 } from 'lucide-react'
import type { CriteriaDraftAction, CriteriaDraftState, ScreeningQuestion } from './criteria-types'
import ParameterBuilder from './parameter-builder'
import type { CriteriaDiagnostic } from './criteria-validation'
import CitationFieldSelector, { type CitationFieldContract } from './citation-field-selector'
import ContextEditorDialog from './context-editor-dialog'

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
  collapsed,
  onToggle,
  citationFields,
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
  collapsed: boolean
  onToggle: () => void
  citationFields: CitationFieldContract
}) {
  const prefix = `${stage}-${question.id}`
  const [contextAnswerId, setContextAnswerId] = useState<string | null>(null)
  const contextAnswer = question.answers.find((answer) => answer.id === contextAnswerId)
  return (
    <article id={`criteria-item-${question.id}`} className={`rounded-lg border bg-white p-4 ${diagnostics.length ? 'border-red-400' : 'border-gray-200'}`} aria-labelledby={`${prefix}-title`}>
      <div className="flex min-w-0 items-center gap-2">
        <button type="button" aria-expanded={!collapsed} aria-controls={`${prefix}-body`} aria-label={`${collapsed ? labels.expand : labels.collapse} ${labels.question} ${index + 1}`} onClick={onToggle} className="rounded p-1 text-gray-600 hover:bg-gray-100">
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        <strong id={`${prefix}-title`} className="min-w-0 truncate text-sm text-gray-700">
          {labels.question} {index + 1}<span className="font-normal text-gray-500"> — {question.question.trim() || labels.untitledQuestion}</span>
        </strong>
        {diagnostics.length ? <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">{diagnostics.length} {labels.errors}</span> : null}
        <div className="ml-auto flex gap-1">
          <button type="button" aria-label={`${labels.moveUp} ${index + 1}`} disabled={index === 0} onClick={() => dispatch({ type: 'move-question', stage, questionId: question.id, direction: -1 })} className="rounded border p-2 disabled:opacity-40"><ArrowUp className="h-4 w-4" /></button>
          <button type="button" aria-label={`${labels.moveDown} ${index + 1}`} disabled={index === count - 1} onClick={() => dispatch({ type: 'move-question', stage, questionId: question.id, direction: 1 })} className="rounded border p-2 disabled:opacity-40"><ArrowDown className="h-4 w-4" /></button>
          <button type="button" aria-label={`${labels.deleteQuestion} ${index + 1}`} onClick={() => {
            if (!sourceReferenced || window.confirm(labels.deleteDependencyWarning)) dispatch({ type: 'delete-question', stage, questionId: question.id })
          }} className="rounded border border-red-200 p-2 text-red-700"><Trash2 className="h-4 w-4" /></button>
        </div>
      </div>
      {!collapsed ? <div id={`${prefix}-body`}>
      <label className="mt-3 block text-sm font-medium" htmlFor={`${prefix}-question`}>{labels.questionText}</label>
      <input id={`${prefix}-question`} value={question.question} onChange={(event) => dispatch({ type: 'update-question', stage, questionId: question.id, field: 'question', value: event.target.value })} className="mt-1 w-full rounded-md border px-3 py-2" />
      <div className="mt-3 rounded-md border border-dashed border-emerald-300 bg-emerald-50/40 p-3">
        <label className="block text-sm font-medium" htmlFor={`${prefix}-answer-column`}>{question.answer_column ? labels.answerColumn : `+ ${labels.addAnswerColumn}`}</label>
        <p className="mt-1 text-xs text-gray-600">{labels.answerColumnTooltip}</p>
        <select id={`${prefix}-answer-column`} value={question.answer_column || ''} onChange={(event) => dispatch({ type: 'set-answer-column', itemId: question.id, value: event.target.value || null })} className="mt-2 w-full rounded-md border px-2 py-1.5 text-sm" title={labels.answerColumnTooltip}>
          {question.answer_column && !citationFields.fields.some((field) => field.name === question.answer_column) ? <option value={question.answer_column}>{question.answer_column} · {labels.unavailableField}</option> : null}
          <option value="">{labels.noAnswerColumn}</option>
          {citationFields.fields.map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}
        </select>
      </div>
      <fieldset className="mt-4 space-y-3">
        <legend className="text-sm font-semibold">{labels.answers}</legend>
        {question.answers.map((answer, answerIndex) => (
          <div key={answer.id} className="rounded-md bg-gray-50 p-3">
            <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto_auto]">
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
              <button type="button" aria-label={`${labels.editAnswerContext} ${answerIndex + 1}`} onClick={() => setContextAnswerId(answer.id)} className="self-end rounded border p-2 text-gray-700" title={labels.editAnswerContext}><Pencil className="h-4 w-4" /></button>
              <button type="button" aria-label={`${labels.deleteAnswer} ${answerIndex + 1}`} disabled={question.answers.length <= 2} onClick={() => {
                if (!referencedAnswerIds.has(answer.id) || window.confirm(labels.deleteDependencyWarning)) dispatch({ type: 'delete-answer', stage, questionId: question.id, answerId: answer.id })
              }} className="self-end rounded border border-red-200 p-2 text-red-700 disabled:opacity-40"><Trash2 className="h-4 w-4" /></button>
            </div>
            {answer.context?.trim() ? <p className="mt-2 text-xs font-medium text-emerald-700">{labels.contextAdded}</p> : null}
          </div>
        ))}
      </fieldset>
      <button type="button" onClick={() => dispatch({ type: 'add-answer', stage, questionId: question.id })} className="mt-3 inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm"><Plus className="h-4 w-4" />{labels.addAnswer}</button>
      <fieldset className="mt-3 space-y-3">
        <legend className="sr-only">{labels.triggers}</legend>
        <div className="flex items-center gap-3 rounded-md bg-gray-50 p-3">
          <div className="min-w-0"><p className="text-sm font-medium">{labels.triggers}</p><p className="text-xs text-gray-600">{question.trigger.all.length ? `${question.trigger.all.length} ${labels.conditionsConfigured}` : labels.alwaysShown}</p></div>
          <button type="button" aria-label={labels.addTrigger} title={labels.addTrigger} disabled={sources.length === 0} onClick={() => {
            const source = sources[0]
            const answer = source?.question.answers[0]
            if (source && answer) dispatch({ type: 'add-trigger', stage, questionId: question.id, sourceItemId: source.question.id, optionId: answer.id })
          }} className="ml-auto inline-flex shrink-0 rounded border border-gray-300 bg-white p-2 text-gray-700 hover:bg-gray-100 disabled:opacity-40"><Plus className="h-4 w-4" /></button>
        </div>
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
      </fieldset>
      {diagnostics.length ? <ul className="mt-3 list-disc rounded bg-red-50 p-3 pl-8 text-sm text-red-800">{diagnostics.map((item) => <li key={`${item.path}-${item.message}`}>{item.message}</li>)}</ul> : null}
      </div> : null}
      <ContextEditorDialog
        open={Boolean(contextAnswer)}
        title={labels.editAnswerContext}
        description={contextAnswer ? `${labels.answerContextFor} “${contextAnswer.label}”` : labels.answerContext}
        label={labels.answerContext}
        value={contextAnswer?.context || ''}
        cancelLabel={labels.cancel}
        saveLabel={labels.saveContext}
        onOpenChange={(open) => { if (!open) setContextAnswerId(null) }}
        onSave={(value) => { if (contextAnswer) dispatch({ type: 'update-answer', stage, questionId: question.id, answerId: contextAnswer.id, field: 'context', value }) }}
      />
    </article>
  )
}

export default function CriteriaBuilder({ state, dispatch, labels, diagnostics = [], citationFields = { fields: [], unavailable_configured_fields: [] } }: Props) {
  const [collapsedSections, setCollapsedSections] = useState<Record<'l1' | 'l2', boolean>>({ l1: false, l2: false })
  const [collapsedQuestions, setCollapsedQuestions] = useState<Set<string>>(() => new Set())
  const pendingQuestion = useRef<{ stage: 'l1' | 'l2'; previousCount: number } | null>(null)
  const ordered: SourceOption[] = [
    ...state.criteria.l1.map((question) => ({ stage: 'l1' as const, question })),
    ...state.criteria.l2.map((question) => ({ stage: 'l2' as const, question })),
  ]
  const l1Questions = state.criteria.l1
  const l2Questions = state.criteria.l2
  const conditions = [...state.criteria.l1, ...state.criteria.l2, ...state.criteria.parameters].flatMap((item) => item.trigger.all)

  useEffect(() => {
    const pending = pendingQuestion.current
    const questions = pending?.stage === 'l1' ? l1Questions : l2Questions
    if (!pending || questions.length <= pending.previousCount) return
    const question = questions.at(-1)
    pendingQuestion.current = null
    if (!question) return
    setCollapsedQuestions((current) => {
      const next = new Set(current)
      next.delete(question.id)
      return next
    })
    const item = document.getElementById(`criteria-item-${question.id}`)
    item?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    document.getElementById(`${pending.stage}-${question.id}-question`)?.focus()
  }, [l1Questions, l2Questions])

  const addQuestion = (stage: 'l1' | 'l2') => {
    pendingQuestion.current = { stage, previousCount: state.criteria[stage].length }
    setCollapsedSections((current) => ({ ...current, [stage]: false }))
    dispatch({ type: 'add-question', stage })
  }

  const cycleSection = (stage: 'l1' | 'l2') => {
    const ids = state.criteria[stage].map((question) => question.id)
    if (collapsedSections[stage]) {
      setCollapsedSections((current) => ({ ...current, [stage]: false }))
      setCollapsedQuestions((current) => new Set([...current, ...ids]))
      return
    }
    const allCardsCollapsed = ids.length > 0 && ids.every((id) => collapsedQuestions.has(id))
    if (allCardsCollapsed) {
      setCollapsedQuestions((current) => { const next = new Set(current); ids.forEach((id) => next.delete(id)); return next })
      return
    }
    setCollapsedSections((current) => ({ ...current, [stage]: true }))
  }

  return (
    <div className="space-y-6">
      <CitationFieldSelector state={state} dispatch={dispatch} contract={citationFields} labels={labels} />
      {(['l1', 'l2'] as const).map((stage) => (
        <section key={stage} className="space-y-3" aria-labelledby={`${stage}-heading`}>
          <div className="flex items-center gap-2 rounded-md bg-gray-50 p-2">
            {(() => {
              const ids = state.criteria[stage].map((question) => question.id)
              const allCardsCollapsed = ids.length > 0 && ids.every((id) => collapsedQuestions.has(id))
              const action = collapsedSections[stage] ? labels.maximizeSection : allCardsCollapsed ? labels.maximizeAll : labels.minimizeAll
              return <button type="button" data-state={collapsedSections[stage] ? 'minimized' : allCardsCollapsed ? 'items-minimized' : 'expanded'} aria-expanded={!collapsedSections[stage]} aria-controls={`${stage}-items`} aria-label={`${action} ${stage === 'l1' ? labels.l1 : labels.l2}`} title={action} onClick={() => cycleSection(stage)} className="rounded p-1 text-gray-600 hover:bg-gray-200">
                {collapsedSections[stage] ? <ChevronUp className="h-5 w-5" /> : allCardsCollapsed ? <ChevronDown className="h-5 w-5" /> : <ChevronsDown className="h-5 w-5" />}
              </button>
            })()}
            <h4 id={`${stage}-heading`} className="font-semibold">{stage === 'l1' ? labels.l1 : labels.l2} <span className="font-normal text-gray-500">({state.criteria[stage].length})</span></h4>
            {diagnostics.filter((item) => state.criteria[stage].some((question) => question.id === item.itemId)).length ? <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">{diagnostics.filter((item) => state.criteria[stage].some((question) => question.id === item.itemId)).length} {labels.errors}</span> : null}
            <button type="button" onClick={() => addQuestion(stage)} className="ml-auto inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white"><Plus className="h-4 w-4" />{labels.addQuestion}</button>
          </div>
          {!collapsedSections[stage] ? <div id={`${stage}-items`} className="space-y-3">
          {state.criteria[stage].length === 0 ? <p className="rounded-md border border-dashed p-4 text-sm text-gray-500">{labels.noQuestions}</p> : null}
          {state.criteria[stage].map((question, index) => {
            const position = ordered.findIndex((item) => item.question.id === question.id)
            return <QuestionCard key={question.id} question={question} index={index} count={state.criteria[stage].length} stage={stage} dispatch={dispatch} labels={labels} sources={ordered.slice(0, position)} citationFields={citationFields} diagnostics={diagnostics.filter((item) => item.itemId === question.id)} sourceReferenced={conditions.some((condition) => condition.source_item_id === question.id)} referencedAnswerIds={new Set(conditions.filter((condition) => condition.source_item_id === question.id).map((condition) => condition.option_id))} collapsed={collapsedQuestions.has(question.id)} onToggle={() => setCollapsedQuestions((current) => { const next = new Set(current); if (next.has(question.id)) next.delete(question.id); else next.add(question.id); return next })} />
          })}
          <div className="flex justify-end"><button type="button" onClick={() => addQuestion(stage)} className="inline-flex items-center gap-2 rounded-md border border-emerald-600 px-3 py-2 text-sm font-medium text-emerald-700"><Plus className="h-4 w-4" />{labels.addQuestion}</button></div>
          </div> : null}
        </section>
      ))}
      <ParameterBuilder state={state} dispatch={dispatch} labels={labels} diagnostics={diagnostics} citationFields={citationFields} />
    </div>
  )
}
