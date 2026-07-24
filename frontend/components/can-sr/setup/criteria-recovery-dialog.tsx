import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

export type RecoveryMode = 'conflict' | 'reload'

export default function CriteriaRecoveryDialog({ mode, labels, onCancel, onReload, onExport }: {
  mode: RecoveryMode | null
  labels: Record<string, string>
  onCancel: () => void
  onReload: () => void
  onExport: () => void
}) {
  if (!mode) return null
  const conflict = mode === 'conflict'
  return <Dialog open onOpenChange={(open) => { if (!open) onCancel() }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{conflict ? labels.conflictTitle : labels.reloadTitle}</DialogTitle>
        <DialogDescription>{conflict ? labels.conflictDescription : labels.reloadDescription}</DialogDescription>
      </DialogHeader>
      {conflict ? <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-950">{labels.conflictPreserved}</p> : null}
      <DialogFooter className="sm:justify-between">
        <button type="button" onClick={onCancel} className="rounded-md border px-4 py-2 text-sm">{labels.cancel}</button>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <button type="button" onClick={onExport} className="rounded-md border px-4 py-2 text-sm">{labels.exportLocalDraft}</button>
          <button type="button" onClick={onReload} className="rounded-md bg-red-700 px-4 py-2 text-sm font-medium text-white">{labels.discardAndReload}</button>
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
