import { describe, expect, it } from 'vitest'
import { emptyCriteria } from './criteria-types'
import { backendDiagnostics, validateCriteriaDraft } from './criteria-validation'

describe('criteria validation', () => {
  it('maps invalid item fields and trigger dependencies to actionable diagnostics', () => {
    const criteria = emptyCriteria()
    criteria.l1 = [{
      id: 'question_one', question: '',
      answers: [{ id: 'answer_yes', label: '', decision: 'include' }, { id: 'answer_no', label: 'No', decision: 'exclude' }],
      trigger: { all: [{ source_item_id: 'missing_item', option_id: 'missing_option' }] },
    }]
    const diagnostics = validateCriteriaDraft(criteria)
    expect(diagnostics.map((item) => item.path)).toEqual(expect.arrayContaining(['l1.0.question', 'l1.0.answers.0.label', 'l1.0.trigger.all.0']))
    expect(diagnostics.every((item) => item.itemId === 'question_one')).toBe(true)
  })

  it('normalizes FastAPI validation errors without exposing another data model', () => {
    expect(backendDiagnostics([{ loc: ['body', 'parameters', 0, 'name'], msg: 'Field required' }])).toEqual([
      { path: 'parameters.0.name', message: 'Field required' },
    ])
  })
})
