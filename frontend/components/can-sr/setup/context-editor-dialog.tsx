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

type Props = {
  open: boolean
  title: string
  description: string
  label: string
  value: string
  cancelLabel: string
  saveLabel: string
  onOpenChange: (open: boolean) => void
  onSave: (value: string) => void
}

export default function ContextEditorDialog({
  open,
  title,
  description,
  label,
  value,
  cancelLabel,
  saveLabel,
  onOpenChange,
  onSave,
}: Props) {
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    if (open) setDraft(value)
  }, [open, value])

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="sm:max-w-xl">
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      <div>
        <label className="block text-sm font-medium" htmlFor="context-dialog-value">{label}</label>
        <textarea
          id="context-dialog-value"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="mt-1 min-h-40 w-full rounded-md border px-3 py-2"
        />
      </div>
      <DialogFooter>
        <button type="button" onClick={() => onOpenChange(false)} className="rounded-md border px-4 py-2 text-sm font-medium">{cancelLabel}</button>
        <button type="button" onClick={() => { onSave(draft); onOpenChange(false) }} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white">{saveLabel}</button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
