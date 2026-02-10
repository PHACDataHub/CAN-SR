'use client'

import Link from 'next/link'
import { useState } from 'react'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import { Button } from '@/components/ui/button'

interface StackingCardProps {
  title: string
  description?: string
  href: string
  className?: string
}

export default function StackingCard({ title, description, href, className }: StackingCardProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className={`w-full ${className || ''}`}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <div
          className={`flex cursor-pointer items-center justify-between rounded-lg border border-gray-200 bg-white/90 p-4 shadow-sm transition-all hover:shadow-md`}
        >
          <div onClick={() => setOpen(!open)} className="flex-1">
            <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
            {description && <p className="mt-1 text-sm text-gray-600">{description}</p>}
          </div>

          <div className="ml-4 flex items-center space-x-3">
            {/* <button
              aria-label={open ? 'Collapse' : 'Expand'}
              onClick={() => setOpen(!open)}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
              type="button"
            >
              {open ? 'Minimize' : 'Expand'}
            </button> */}

            <Link href={href} className="rounded-md border border-emerald-500 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100">
              
                Open
              
            </Link>
          </div>
        </div>

        <CollapsibleContent>
          <div className="rounded-b-lg border border-t-0 border-gray-200 bg-white/95 p-4 text-sm text-gray-700">
            <p className="mb-3">
              {description || 'Open to view details and continue to the next step.'}
            </p>
            {/* <div className="flex justify-end">
              <Link href={href}>
                <Button className="rounded-md bg-emerald-600 text-white hover:bg-emerald-700">Go to step</Button>
              </Link>
            </div> */}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
