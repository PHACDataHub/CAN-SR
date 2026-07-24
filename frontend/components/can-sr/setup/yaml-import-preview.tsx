import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type { CriteriaConfig } from './criteria-types'

export type ImportDiagnostic = {
  severity: 'info' | 'warning'
  code: string
  message: string
  requires_confirmation?: boolean
}

export type CriteriaImportPreview = {
  criteria: CriteriaConfig
  source_format: 'criteria_v2' | 'legacy_yaml_v1'
  diagnostics: ImportDiagnostic[]
  requires_confirmation: boolean
  fingerprint?: string | null
  stats?: { l1: number; l2: number; parameters: number } | null
}

export default function YamlImportPreview({ preview, labels, onCancel, onAccept }: {
  preview: CriteriaImportPreview | null
  labels: Record<string, string>
  onCancel: () => void
  onAccept: () => void
}) {
  if (!preview) return null
  const stats = preview.stats || {
    l1: preview.criteria.l1.length, l2: preview.criteria.l2.length, parameters: preview.criteria.parameters.length,
  }
  return <Dialog open onOpenChange={(open) => { if (!open) onCancel() }}>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{labels.importPreviewTitle}</DialogTitle>
        <DialogDescription>{labels.importPreviewDescription}</DialogDescription>
      </DialogHeader>
      <dl className="grid gap-3 rounded-md bg-gray-50 p-4 text-sm sm:grid-cols-3">
        <div><dt className="font-medium">{labels.l1}</dt><dd>{stats.l1} {labels.questionsCount}</dd></div>
        <div><dt className="font-medium">{labels.l2}</dt><dd>{stats.l2} {labels.questionsCount}</dd></div>
        <div><dt className="font-medium">{labels.parameters}</dt><dd>{stats.parameters} {labels.parametersCount}</dd></div>
      </dl>
      <p className="text-sm"><strong>{labels.importFormat}:</strong> {preview.source_format === 'legacy_yaml_v1' ? labels.legacyYaml : labels.canonicalYaml}</p>
      {preview.diagnostics.length ? <section aria-labelledby="import-warnings-heading">
        <h4 id="import-warnings-heading" className="font-semibold">{labels.importWarnings}</h4>
        <ul className="mt-2 space-y-2">{preview.diagnostics.map((item, index) => <li key={`${item.code}-${index}`} className={`rounded-md p-3 text-sm ${item.requires_confirmation ? 'bg-amber-100 text-amber-950' : 'bg-blue-50 text-blue-900'}`}><strong>{item.code}</strong>: {item.message}</li>)}</ul>
      </section> : <p className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">{labels.importNoWarnings}</p>}
      {preview.requires_confirmation ? <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">{labels.importConfirmationRequired}</p> : null}
      <DialogFooter>
        <button type="button" onClick={onCancel} className="rounded-md border px-4 py-2 text-sm">{labels.cancelImport}</button>
        <button type="button" onClick={onAccept} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white">{labels.replaceDraft}</button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
