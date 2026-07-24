import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { emptyCriteria } from './criteria-types'
import YamlImportPreview, { type CriteriaImportPreview } from './yaml-import-preview'

const labels = new Proxy({}, { get: (_target, property) => String(property) }) as Record<string, string>

function preview(overrides: Partial<CriteriaImportPreview> = {}): CriteriaImportPreview {
  return {
    criteria: emptyCriteria(), source_format: 'legacy_yaml_v1', diagnostics: [],
    requires_confirmation: false, stats: { l1: 2, l2: 1, parameters: 3 }, ...overrides,
  }
}

describe('YamlImportPreview', () => {
  it('shows normalized counts and accepts replacement explicitly', async () => {
    const user = userEvent.setup()
    const accept = vi.fn()
    render(<YamlImportPreview preview={preview()} labels={labels} onCancel={vi.fn()} onAccept={accept} />)
    expect(screen.getByRole('dialog', { name: 'importPreviewTitle' })).toBeInTheDocument()
    expect(screen.getByText('2 questionsCount')).toBeInTheDocument()
    expect(screen.getByText('3 parametersCount')).toBeInTheDocument()
    expect(screen.getByText('legacyYaml')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'replaceDraft' }))
    expect(accept).toHaveBeenCalledOnce()
  })

  it('surfaces required migration review and preserves the draft on cancel', async () => {
    const user = userEvent.setup()
    const cancel = vi.fn()
    render(<YamlImportPreview preview={preview({
      requires_confirmation: true,
      diagnostics: [{ severity: 'warning', code: 'decision_inferred_exclude', message: 'Decision inferred.', requires_confirmation: true }],
    })} labels={labels} onCancel={cancel} onAccept={vi.fn()} />)
    expect(screen.getByText(/decision_inferred_exclude/)).toBeInTheDocument()
    expect(screen.getByText('importConfirmationRequired')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'cancelImport' }))
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('does not render before a successful backend preview exists', () => {
    render(<YamlImportPreview preview={null} labels={labels} onCancel={vi.fn()} onAccept={vi.fn()} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
