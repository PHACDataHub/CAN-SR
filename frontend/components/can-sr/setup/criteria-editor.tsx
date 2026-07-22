'use client'

import { useCallback, useEffect, useReducer, useState } from 'react'
import { authenticatedFetch } from '@/lib/auth'
import CriteriaBuilder from './criteria-builder'
import { criteriaDraftReducer, emptyCriteria, type CriteriaConfig } from './criteria-types'

type Props = { srId: string; labels: Record<string, string>; hasScreeningData: boolean }

export default function CriteriaEditor({ srId, labels, hasScreeningData }: Props) {
  const [state, dispatch] = useReducer(criteriaDraftReducer, { criteria: emptyCriteria(), revision: 0, dirty: false })
  const [status, setStatus] = useState(labels.loading)
  const [migrationFingerprint, setMigrationFingerprint] = useState<string | null>(null)
  const [force, setForce] = useState(false)

  const endpoint = `/api/can-sr/reviews/criteria-config?sr_id=${encodeURIComponent(srId)}`
  const load = useCallback(async () => {
    setStatus(labels.loading)
    const response = await authenticatedFetch(endpoint)
    const data = await response.json().catch(() => ({}))
    if (!response.ok) { setStatus(data?.detail || labels.loadFailed); return }
    dispatch({ type: 'replace', criteria: data.criteria as CriteriaConfig, revision: data.revision || 0 })
    setMigrationFingerprint(data?.migration?.fingerprint || null)
    setStatus(data?.migration?.requires_confirmation ? labels.migrationWarning : '')
  }, [endpoint, labels])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (state.dirty) event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [state.dirty])

  const save = async () => {
    setStatus(labels.saving)
    const response = await authenticatedFetch(endpoint, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criteria: state.criteria, expected_revision: state.revision, force, migration_fingerprint: migrationFingerprint }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      const detail = data?.detail
      setStatus(typeof detail === 'string' ? detail : detail?.message || labels.saveFailed)
      return
    }
    dispatch({ type: 'replace', criteria: data.criteria, revision: data.revision })
    setMigrationFingerprint(null); setForce(false); setStatus(labels.saved)
  }

  const importYaml = async (file: File | null) => {
    if (!file) return
    const response = await authenticatedFetch(`${endpoint}&operation=import-yaml`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ criteria_yaml: await file.text() }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) { setStatus(data?.detail?.errors?.[0]?.message || labels.importFailed); return }
    dispatch({ type: 'replace', criteria: data.criteria, revision: state.revision })
    dispatch({ type: 'set-citation-fields', value: data.criteria.citation_fields.l1_include })
    setMigrationFingerprint(data.fingerprint || null)
    setStatus(data.requires_confirmation ? labels.migrationWarning : labels.imported)
  }

  const downloadYaml = async () => {
    const response = await authenticatedFetch(`${endpoint}&download=yaml`)
    if (!response.ok) { setStatus(labels.downloadFailed); return }
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = 'criteria.yaml'; anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section aria-labelledby="visual-criteria-heading">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="mr-auto"><h3 id="visual-criteria-heading" className="text-lg font-semibold">{labels.visualBuilder}</h3><p className="text-sm text-gray-600">{labels.visualBuilderDesc}</p></div>
        <label className="cursor-pointer rounded-md border px-3 py-2 text-sm">{labels.importYaml}<input className="sr-only" type="file" accept=".yaml,.yml,text/yaml" onChange={(event) => void importYaml(event.target.files?.[0] || null)} /></label>
        <button type="button" onClick={() => void downloadYaml()} className="rounded-md border px-3 py-2 text-sm">{labels.downloadYaml}</button>
        <button type="button" onClick={() => void load()} className="rounded-md border px-3 py-2 text-sm">{labels.reload}</button>
        <button type="button" disabled={!state.dirty} onClick={() => void save()} className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{labels.save}</button>
      </div>
      {hasScreeningData ? <label className="mb-4 flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm"><input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />{labels.confirmInvalidation}</label> : null}
      <div role="status" aria-live="polite" className="mb-3 text-sm text-gray-600">{status}{state.dirty ? ` · ${labels.unsaved}` : ''}</div>
      <CriteriaBuilder state={state} dispatch={dispatch} labels={labels} />
    </section>
  )
}
