'use client'

import { useEffect, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export type ParameterDetails = {
  description: string
  unit_instructions: string
  calculation: string
}

type Props = {
  open: boolean
  parameterName: string
  value: ParameterDetails
  labels: Record<string, string>
  onOpenChange: (open: boolean) => void
  onSave: (value: ParameterDetails) => void
}

export default function ParameterDetailsDialog({ open, parameterName, value, labels, onOpenChange, onSave }: Props) {
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    if (open) setDraft(value)
  }, [open, value])

  const update = (field: keyof ParameterDetails, next: string) => setDraft((current) => ({ ...current, [field]: next }))

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{labels.editParameterDetails}</DialogTitle>
        <DialogDescription>{labels.parameterDetailsFor} “{parameterName || labels.untitledParameter}”</DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium" htmlFor="parameter-details-description">{labels.parameterDescription}</label>
          <textarea id="parameter-details-description" value={draft.description} onChange={(event) => update('description', event.target.value)} className="mt-1 min-h-28 w-full rounded-md border px-3 py-2" />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="parameter-details-units">{labels.unitInstructions}</label>
          <textarea id="parameter-details-units" value={draft.unit_instructions} onChange={(event) => update('unit_instructions', event.target.value)} className="mt-1 min-h-28 w-full rounded-md border px-3 py-2" />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="parameter-details-calculation">{labels.calculation}</label>
          <textarea id="parameter-details-calculation" value={draft.calculation} onChange={(event) => update('calculation', event.target.value)} className="mt-1 min-h-28 w-full rounded-md border px-3 py-2" />
        </div>
      </div>
      <DialogFooter>
        <button type="button" onClick={() => onOpenChange(false)} className="rounded-md border px-4 py-2 text-sm font-medium">{labels.cancel}</button>
        <button type="button" onClick={() => { onSave(draft); onOpenChange(false) }} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white">{labels.saveDetails}</button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
