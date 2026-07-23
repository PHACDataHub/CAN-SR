import type { CriteriaConfig, Parameter, ScreeningQuestion } from './criteria-types'

export type CriteriaDiagnostic = { path: string; message: string; itemId?: string }

const idPattern = /^[a-z][a-z0-9_-]{2,63}$/

export function validateCriteriaDraft(criteria: CriteriaConfig): CriteriaDiagnostic[] {
  const diagnostics: CriteriaDiagnostic[] = []
  const seenIds = new Set<string>()
  const available = new Map<string, Set<string> | null>()
  const add = (path: string, message: string, itemId?: string) => diagnostics.push({ path, message, itemId })

  const validateId = (id: string, path: string, itemId: string) => {
    if (!idPattern.test(id)) add(path, 'The stable ID has an invalid format.', itemId)
    if (seenIds.has(id)) add(path, 'The stable ID must be unique across the review.', itemId)
    seenIds.add(id)
  }
  const validateTrigger = (item: ScreeningQuestion | Parameter, path: string) => {
    const pairs = new Set<string>()
    item.trigger.all.forEach((condition, index) => {
      const conditionPath = `${path}.trigger.all.${index}`
      const options = available.get(condition.source_item_id)
      if (!available.has(condition.source_item_id)) add(conditionPath, 'Trigger source must be an earlier item.', item.id)
      else if (options === null) add(conditionPath, 'Free-text parameters cannot be trigger sources.', item.id)
      else if (options && !options.has(condition.option_id)) add(conditionPath, 'The selected source answer or option no longer exists.', item.id)
      const pair = `${condition.source_item_id}:${condition.option_id}`
      if (pairs.has(pair)) add(conditionPath, 'Duplicate trigger conditions are not allowed.', item.id)
      pairs.add(pair)
    })
  }

  ;(['l1', 'l2'] as const).forEach((stage) => criteria[stage].forEach((question, index) => {
    const path = `${stage}.${index}`
    validateId(question.id, `${path}.id`, question.id)
    if (!question.question.trim()) add(`${path}.question`, 'Question text is required.', question.id)
    if (question.answers.length < 2) add(`${path}.answers`, 'At least two answers are required.', question.id)
    const answerIds = new Set<string>()
    question.answers.forEach((answer, answerIndex) => {
      if (!idPattern.test(answer.id) || answerIds.has(answer.id)) add(`${path}.answers.${answerIndex}.id`, 'Answer IDs must be valid and unique within the question.', question.id)
      if (!answer.label.trim()) add(`${path}.answers.${answerIndex}.label`, 'Answer label is required.', question.id)
      answerIds.add(answer.id)
    })
    validateTrigger(question, path)
    available.set(question.id, answerIds)
  }))

  criteria.parameters.forEach((parameter, index) => {
    const path = `parameters.${index}`
    validateId(parameter.id, `${path}.id`, parameter.id)
    if (!parameter.name.trim()) add(`${path}.name`, 'Parameter name is required.', parameter.id)
    if (!parameter.description.trim()) add(`${path}.description`, 'Parameter description is required.', parameter.id)
    validateTrigger(parameter, path)
    if (parameter.type === 'selection') {
      if (parameter.options.length < 1) add(`${path}.options`, 'At least one selection option is required.', parameter.id)
      const optionIds = new Set<string>()
      parameter.options.forEach((option, optionIndex) => {
        if (!idPattern.test(option.id) || optionIds.has(option.id)) add(`${path}.options.${optionIndex}.id`, 'Option IDs must be valid and unique within the parameter.', parameter.id)
        if (!option.label.trim()) add(`${path}.options.${optionIndex}.label`, 'Option label is required.', parameter.id)
        optionIds.add(option.id)
      })
      available.set(parameter.id, optionIds)
    } else available.set(parameter.id, null)
  })
  return diagnostics
}

export function backendDiagnostics(detail: unknown): CriteriaDiagnostic[] {
  const errors = typeof detail === 'object' && detail && 'errors' in detail ? (detail as { errors?: unknown[] }).errors : Array.isArray(detail) ? detail : []
  return (errors || []).map((error) => {
    const value = error as { loc?: Array<string | number>; path?: Array<string | number>; msg?: string; message?: string }
    const location = value.loc?.filter((part) => part !== 'body') || value.path || []
    return { path: location.join('.'), message: value.message || value.msg || 'Invalid criteria configuration.' }
  })
}
