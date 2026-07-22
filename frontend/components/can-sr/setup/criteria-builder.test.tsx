import { useReducer } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import CriteriaBuilder from './criteria-builder'
import { criteriaDraftReducer, emptyCriteria } from './criteria-types'

const labels = new Proxy({}, { get: (_target, property) => String(property) }) as Record<string, string>

function Harness() {
  const [state, dispatch] = useReducer(criteriaDraftReducer, { criteria: emptyCriteria(), revision: 0, dirty: false })
  return <><CriteriaBuilder state={state} dispatch={dispatch} labels={labels} /><output>{state.dirty ? 'dirty' : 'clean'}</output></>
}

describe('CriteriaBuilder', () => {
  it('adds an accessible question with explicit decisions', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getAllByRole('button', { name: /addQuestion/ })[0])
    expect(screen.getByLabelText('questionText')).toHaveValue('New screening question')
    expect(screen.getAllByLabelText('decision')).toHaveLength(2)
    expect(screen.getAllByLabelText('decision')[1]).toHaveValue('exclude')
    expect(screen.getByText('dirty')).toBeInTheDocument()
  })

  it('supports keyboard-operable move controls', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const add = screen.getAllByRole('button', { name: /addQuestion/ })[0]
    await user.click(add); await user.click(add)
    const questions = screen.getAllByLabelText('questionText')
    await user.clear(questions[0]); await user.type(questions[0], 'First')
    await user.clear(questions[1]); await user.type(questions[1], 'Second')
    await user.click(screen.getByRole('button', { name: 'moveUp 2' }))
    expect(screen.getAllByLabelText('questionText').map((input) => (input as HTMLInputElement).value)).toEqual(['Second', 'First'])
  })

  it('offers only earlier questions and retains forward references as actionable errors', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const addQuestion = screen.getAllByRole('button', { name: /addQuestion/ })[0]
    await user.click(addQuestion); await user.click(addQuestion)
    const questions = screen.getAllByLabelText('questionText')
    await user.clear(questions[0]); await user.type(questions[0], 'Earlier question')
    await user.clear(questions[1]); await user.type(questions[1], 'Dependent question')

    const addConditions = screen.getAllByRole('button', { name: 'addTrigger' })
    expect(addConditions[0]).toBeDisabled()
    expect(addConditions[1]).toBeEnabled()
    await user.click(addConditions[1])
    expect(screen.getByLabelText('triggerSource')).toHaveDisplayValue('Earlier question')
    expect(screen.getByLabelText('triggerAnswer')).toHaveDisplayValue('Yes')

    await user.click(screen.getByRole('button', { name: 'moveUp 2' }))
    expect(screen.getByRole('alert')).toHaveTextContent('triggerOrderError')
    expect(screen.getByRole('button', { name: 'removeTrigger 1' })).toBeEnabled()
  })

  it('surfaces a missing source after deletion without silently removing the trigger', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const addQuestion = screen.getAllByRole('button', { name: /addQuestion/ })[0]
    await user.click(addQuestion); await user.click(addQuestion)
    await user.click(screen.getAllByRole('button', { name: 'addTrigger' })[1])
    await user.click(screen.getByRole('button', { name: 'deleteQuestion 1' }))
    expect(screen.getByRole('alert')).toHaveTextContent('triggerOrderError')
    expect(screen.getByRole('button', { name: 'removeTrigger 1' })).toBeInTheDocument()
  })
})
