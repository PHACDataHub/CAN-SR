import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CriteriaPreview from './criteria-preview'
import { emptyCriteria } from './criteria-types'
import { backendDiagnostics, validateCriteriaDraft } from './criteria-validation'

const labels = new Proxy({}, { get: (_target, property) => String(property) }) as Record<string, string>

describe('criteria validation and preview', () => {
  it('maps invalid item fields and trigger dependencies to actionable diagnostics', () => {
    const criteria = emptyCriteria()
    criteria.l1 = [{
      id: 'question_one', question: '', context: '',
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

  it('renders a readable summary directly from the canonical draft', () => {
    const criteria = emptyCriteria()
    criteria.citation_fields.l1_include = ['Title', 'Abstract']
    criteria.parameters = [{ id: 'parameter_age', name: 'Age', description: 'Age', type: 'text', trigger: { all: [] } }]
    render(<CriteriaPreview criteria={criteria} labels={labels} />)
    expect(screen.getByText('1 parametersCount')).toBeInTheDocument()
    expect(screen.getByText(/Title, Abstract/)).toBeInTheDocument()
    expect(screen.getByText(/1 freeText/)).toBeInTheDocument()
  })
})
