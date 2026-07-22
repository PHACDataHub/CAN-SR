export type Decision = 'include' | 'exclude'

export type ScreeningAnswer = {
  id: string
  label: string
  context?: string | null
  decision: Decision
}

export type ScreeningQuestion = {
  id: string
  question: string
  context?: string | null
  answers: ScreeningAnswer[]
  trigger: { all: Array<{ source_item_id: string; option_id: string }> }
}

export type CriteriaConfig = {
  schema_version: 2
  citation_fields: { l1_include: string[]; doi?: string | null }
  l1: ScreeningQuestion[]
  l2: ScreeningQuestion[]
  parameters: unknown[]
}

export type CriteriaDraftState = {
  criteria: CriteriaConfig
  revision: number
  dirty: boolean
}

export type CriteriaDraftAction =
  | { type: 'replace'; criteria: CriteriaConfig; revision: number }
  | { type: 'set-citation-fields'; value: string[] }
  | { type: 'set-doi'; value: string | null }
  | { type: 'add-question'; stage: 'l1' | 'l2' }
  | { type: 'delete-question'; stage: 'l1' | 'l2'; questionId: string }
  | { type: 'move-question'; stage: 'l1' | 'l2'; questionId: string; direction: -1 | 1 }
  | { type: 'update-question'; stage: 'l1' | 'l2'; questionId: string; field: 'question' | 'context'; value: string }
  | { type: 'add-answer'; stage: 'l1' | 'l2'; questionId: string }
  | { type: 'delete-answer'; stage: 'l1' | 'l2'; questionId: string; answerId: string }
  | { type: 'update-answer'; stage: 'l1' | 'l2'; questionId: string; answerId: string; field: 'label' | 'context' | 'decision'; value: string }
  | { type: 'add-trigger'; stage: 'l1' | 'l2'; questionId: string; sourceItemId: string; optionId: string }
  | { type: 'update-trigger'; stage: 'l1' | 'l2'; questionId: string; index: number; sourceItemId: string; optionId: string }
  | { type: 'delete-trigger'; stage: 'l1' | 'l2'; questionId: string; index: number }

export const emptyCriteria = (): CriteriaConfig => ({
  schema_version: 2,
  citation_fields: { l1_include: [], doi: null },
  l1: [],
  l2: [],
  parameters: [],
})

const createId = (prefix: string) => {
  const value = globalThis.crypto?.randomUUID?.().replaceAll('-', '').slice(0, 12)
  return `${prefix}_${value || Math.random().toString(36).slice(2, 14)}`
}

const createAnswer = (label: string, decision: Decision): ScreeningAnswer => ({
  id: createId('answer'),
  label,
  context: '',
  decision,
})

const createQuestion = (): ScreeningQuestion => ({
  id: createId('question'),
  question: 'New screening question',
  context: '',
  answers: [createAnswer('Yes', 'include'), createAnswer('No', 'exclude')],
  trigger: { all: [] },
})

const updateStage = (
  state: CriteriaDraftState,
  stage: 'l1' | 'l2',
  update: (questions: ScreeningQuestion[]) => ScreeningQuestion[],
): CriteriaDraftState => ({
  ...state,
  dirty: true,
  criteria: { ...state.criteria, [stage]: update(state.criteria[stage]) },
})

export function criteriaDraftReducer(
  state: CriteriaDraftState,
  action: CriteriaDraftAction,
): CriteriaDraftState {
  if (action.type === 'replace') {
    return { criteria: action.criteria, revision: action.revision, dirty: false }
  }
  if (action.type === 'set-citation-fields') {
    return { ...state, dirty: true, criteria: { ...state.criteria, citation_fields: { ...state.criteria.citation_fields, l1_include: action.value } } }
  }
  if (action.type === 'set-doi') {
    return { ...state, dirty: true, criteria: { ...state.criteria, citation_fields: { ...state.criteria.citation_fields, doi: action.value } } }
  }
  if (action.type === 'add-question') {
    return updateStage(state, action.stage, (questions) => [...questions, createQuestion()])
  }
  if (action.type === 'delete-question') {
    return updateStage(state, action.stage, (questions) => questions.filter((item) => item.id !== action.questionId))
  }
  if (action.type === 'move-question') {
    return updateStage(state, action.stage, (questions) => {
      const from = questions.findIndex((item) => item.id === action.questionId)
      const to = from + action.direction
      if (from < 0 || to < 0 || to >= questions.length) return questions
      const next = [...questions]
      ;[next[from], next[to]] = [next[to], next[from]]
      return next
    })
  }
  if (action.type === 'update-question') {
    return updateStage(state, action.stage, (questions) => questions.map((item) => item.id === action.questionId ? { ...item, [action.field]: action.value } : item))
  }
  if (action.type === 'add-answer') {
    return updateStage(state, action.stage, (questions) => questions.map((item) => item.id === action.questionId ? { ...item, answers: [...item.answers, createAnswer('New answer', 'include')] } : item))
  }
  if (action.type === 'delete-answer') {
    return updateStage(state, action.stage, (questions) => questions.map((item) => item.id === action.questionId ? { ...item, answers: item.answers.filter((answer) => answer.id !== action.answerId) } : item))
  }
  if (action.type === 'add-trigger') {
    return updateStage(state, action.stage, (questions) => questions.map((item) => item.id === action.questionId ? { ...item, trigger: { all: [...item.trigger.all, { source_item_id: action.sourceItemId, option_id: action.optionId }] } } : item))
  }
  if (action.type === 'update-trigger') {
    return updateStage(state, action.stage, (questions) => questions.map((item) => item.id === action.questionId ? { ...item, trigger: { all: item.trigger.all.map((condition, index) => index === action.index ? { source_item_id: action.sourceItemId, option_id: action.optionId } : condition) } } : item))
  }
  if (action.type === 'delete-trigger') {
    return updateStage(state, action.stage, (questions) => questions.map((item) => item.id === action.questionId ? { ...item, trigger: { all: item.trigger.all.filter((_condition, index) => index !== action.index) } } : item))
  }
  return updateStage(state, action.stage, (questions) => questions.map((item) => {
    if (item.id !== action.questionId) return item
    return { ...item, answers: item.answers.map((answer) => answer.id === action.answerId ? { ...answer, [action.field]: action.value } : answer) }
  }))
}
