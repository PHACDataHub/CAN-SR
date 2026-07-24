import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CriteriaRecoveryDialog from './criteria-recovery-dialog'

const labels = new Proxy({}, { get: (_target, property) => String(property) }) as Record<string, string>

describe('CriteriaRecoveryDialog', () => {
  it('preserves a conflicted draft and offers export or reload', async () => {
    const user = userEvent.setup()
    const exportDraft = vi.fn()
    const reload = vi.fn()
    render(<CriteriaRecoveryDialog mode="conflict" labels={labels} onCancel={vi.fn()} onReload={reload} onExport={exportDraft} />)
    expect(screen.getByRole('dialog', { name: 'conflictTitle' })).toBeInTheDocument()
    expect(screen.getByText('conflictPreserved')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'exportLocalDraft' }))
    expect(exportDraft).toHaveBeenCalledOnce()
    await user.click(screen.getByRole('button', { name: 'discardAndReload' }))
    expect(reload).toHaveBeenCalledOnce()
  })

  it('warns before discarding an ordinary dirty draft', async () => {
    const user = userEvent.setup()
    const cancel = vi.fn()
    render(<CriteriaRecoveryDialog mode="reload" labels={labels} onCancel={cancel} onReload={vi.fn()} onExport={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: 'reloadTitle' })).toBeInTheDocument()
    expect(screen.queryByText('conflictPreserved')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'cancel' }))
    expect(cancel).toHaveBeenCalledOnce()
  })
})
