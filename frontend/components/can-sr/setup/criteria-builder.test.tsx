import { useReducer } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
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
    expect(screen.queryByLabelText('answerContext')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'editAnswerContext 1' }))
    await user.type(screen.getByLabelText('answerContext'), 'Only applies to Yes')
    await user.click(screen.getByRole('button', { name: 'saveContext' }))
    expect(screen.getByText('contextAdded')).toBeInTheDocument()
    expect(screen.getByText('dirty')).toBeInTheDocument()
  })

  it('supports keyboard-operable move controls', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const add = screen.getAllByRole('button', { name: 'addQuestion' })[0]
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
    const addQuestion = screen.getAllByRole('button', { name: 'addQuestion' })[0]
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

  it('uses compact conditional visibility headers with plus controls', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const addQuestion = screen.getAllByRole('button', { name: 'addQuestion' })[0]
    await user.click(addQuestion); await user.click(addQuestion)

    expect(screen.queryByText('triggerDescription')).not.toBeInTheDocument()
    expect(screen.getAllByText('alwaysShown')).toHaveLength(2)
    const addConditions = screen.getAllByRole('button', { name: 'addTrigger' })
    expect(addConditions[0]).toBeDisabled()
    expect(addConditions[1]).toBeEnabled()
    expect(addConditions[1]).toHaveTextContent('')
    await user.click(addConditions[1])
    expect(screen.getByText('1 conditionsConfigured')).toBeInTheDocument()
  })

  it('surfaces a missing source after deletion without silently removing the trigger', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<Harness />)
    const addQuestion = screen.getAllByRole('button', { name: 'addQuestion' })[0]
    await user.click(addQuestion); await user.click(addQuestion)
    await user.click(screen.getAllByRole('button', { name: 'addTrigger' })[1])
    await user.click(screen.getByRole('button', { name: 'deleteQuestion 1' }))
    expect(screen.getByRole('alert')).toHaveTextContent('triggerOrderError')
    expect(screen.getByRole('button', { name: 'removeTrigger 1' })).toBeInTheDocument()
  })

  it('creates typed parameters and preserves options across selection mode changes', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getAllByRole('button', { name: 'addParameter' })[0])
    expect(screen.getByLabelText('parameterType')).toHaveValue('text')
    await user.selectOptions(screen.getByLabelText('parameterType'), 'selection')
    expect(screen.getByLabelText('selectionMode')).toHaveValue('single')
    expect(screen.getByLabelText('optionLabel 1')).toHaveValue('Option 1')
    await user.click(screen.getByRole('button', { name: 'addOption' }))
    await user.type(screen.getByLabelText('optionLabel 2'), 'Eligible option')
    await user.selectOptions(screen.getByLabelText('selectionMode'), 'multiple')
    expect(screen.getByLabelText('optionLabel 2')).toHaveValue('New optionEligible option')
  })

  it('allows later parameter triggers from earlier lists and blocks unsafe conversion to text', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getAllByRole('button', { name: 'addParameter' })[0])
    await user.selectOptions(screen.getByLabelText('parameterType'), 'selection')
    await user.clear(screen.getByLabelText('parameterName')); await user.type(screen.getByLabelText('parameterName'), 'Study design')
    await user.click(screen.getAllByRole('button', { name: 'addParameter' })[0])
    const addConditions = screen.getAllByRole('button', { name: 'addTrigger' })
    await user.click(addConditions[1])
    expect(screen.getByLabelText('triggerSource')).toHaveDisplayValue('Study design')
    expect(screen.getAllByLabelText('parameterType')[0]).toHaveDisplayValue('selectionList')
    expect(screen.getAllByLabelText('parameterType')[0].querySelector('option[value="text"]')).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('typeChangeBlocked')
  })

  it('cycles sections through hidden, visible-with-collapsed-items, and fully expanded states', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getAllByRole('button', { name: 'addQuestion' })[0])
    const question = screen.getByLabelText('questionText')
    await user.clear(question); await user.type(question, 'Is this a randomized trial?')

    expect(screen.getByText((_content, element) => element?.tagName === 'STRONG' && element.textContent?.includes('question 1') === true && element.textContent.includes('Is this a randomized trial?'))).toBeInTheDocument()

    const expandedL1 = screen.getByRole('button', { name: 'minimizeAll l1' })
    expect(expandedL1).toHaveAttribute('data-state', 'expanded')
    expect(expandedL1.querySelector('svg')).toHaveClass('lucide-chevrons-down')
    await user.click(expandedL1)
    expect(screen.queryByRole('button', { name: 'expand question 1' })).not.toBeInTheDocument()
    const minimizedL1 = screen.getByRole('button', { name: 'maximizeSection l1' })
    expect(minimizedL1).toHaveAttribute('data-state', 'minimized')
    expect(minimizedL1.querySelector('svg')).toHaveClass('lucide-chevron-up')
    await user.click(minimizedL1)
    expect(screen.getByRole('button', { name: 'expand question 1' })).toBeInTheDocument()
    const collapsedItemsL1 = screen.getByRole('button', { name: 'maximizeAll l1' })
    expect(collapsedItemsL1).toHaveAttribute('data-state', 'items-minimized')
    expect(collapsedItemsL1.querySelector('svg')).toHaveClass('lucide-chevron-down')
    await user.click(collapsedItemsL1)
    expect(screen.getByLabelText('questionText')).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'addParameter' })[0])
    const expandedParameters = screen.getByRole('button', { name: 'minimizeAll parameters' })
    expect(expandedParameters).toHaveAttribute('data-state', 'expanded')
    expect(expandedParameters.querySelector('svg')).toHaveClass('lucide-chevrons-down')
    await user.click(expandedParameters)
    expect(screen.queryByRole('button', { name: 'expand parameter 1' })).not.toBeInTheDocument()
    const minimizedParameters = screen.getByRole('button', { name: 'maximizeSection parameters' })
    expect(minimizedParameters).toHaveAttribute('data-state', 'minimized')
    expect(minimizedParameters.querySelector('svg')).toHaveClass('lucide-chevron-up')
    await user.click(minimizedParameters)
    expect(screen.getByRole('button', { name: 'expand parameter 1' })).toBeInTheDocument()
    const collapsedItemsParameters = screen.getByRole('button', { name: 'maximizeAll parameters' })
    expect(collapsedItemsParameters).toHaveAttribute('data-state', 'items-minimized')
    expect(collapsedItemsParameters.querySelector('svg')).toHaveClass('lucide-chevron-down')
    await user.click(collapsedItemsParameters)
    expect(screen.getByLabelText('parameterName')).toBeInTheDocument()
  })

  it('supports bottom add controls and focuses newly created items', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const questionButtons = screen.getAllByRole('button', { name: 'addQuestion' })
    await user.click(questionButtons[1])
    expect(screen.getByLabelText('questionText')).toHaveFocus()

    const parameterButtons = screen.getAllByRole('button', { name: 'addParameter' })
    await user.click(parameterButtons.at(-1)!)
    expect(screen.getByLabelText('parameterName')).toHaveFocus()
  })

  it('cancels context edits and saves option context from dialogs', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getAllByRole('button', { name: 'addQuestion' })[0])
    await user.click(screen.getByRole('button', { name: 'editAnswerContext 1' }))
    await user.type(screen.getByLabelText('answerContext'), 'Discard this')
    await user.click(screen.getByRole('button', { name: 'cancel' }))
    expect(screen.queryByText('contextAdded')).not.toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'addParameter' })[0])
    await user.selectOptions(screen.getByLabelText('parameterType'), 'selection')
    await user.click(screen.getByRole('button', { name: 'editOptionContext 1' }))
    await user.type(screen.getByLabelText('optionContext'), 'Select for randomized trials')
    await user.click(screen.getByRole('button', { name: 'saveContext' }))
    expect(screen.getByText('contextAdded')).toBeInTheDocument()
  })

  it('edits long-form parameter details in a dialog instead of inline', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getAllByRole('button', { name: 'addParameter' })[0])

    expect(screen.queryByLabelText('parameterDescription')).not.toBeInTheDocument()
    expect(screen.getByText('1 detailsConfigured')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'editDetails' }))
    expect(screen.getByLabelText('parameterDescription')).toHaveValue('Describe the value to extract')
    await user.type(screen.getByLabelText('unitInstructions'), 'Report in years')
    await user.type(screen.getByLabelText('calculation'), 'Use the adjusted mean')
    await user.click(screen.getByRole('button', { name: 'saveDetails' }))

    expect(screen.queryByLabelText('parameterDescription')).not.toBeInTheDocument()
    expect(screen.getByText('3 detailsConfigured')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'editDetails' }))
    expect(screen.getByLabelText('unitInstructions')).toHaveValue('Report in years')
    expect(screen.getByLabelText('calculation')).toHaveValue('Use the adjusted mean')
  })
})
