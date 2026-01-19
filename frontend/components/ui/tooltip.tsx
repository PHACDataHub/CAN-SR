'use client'

import * as React from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'

interface SimpleTooltipProps {
  children: React.ReactNode
  content: React.ReactNode
  className?: string
}

export function SimpleTooltip({
  children,
  content,
  className,
}: SimpleTooltipProps) {
  const [isVisible, setIsVisible] = React.useState(false)
  const [position, setPosition] = React.useState({ x: 0, y: 0 })
  const triggerRef = React.useRef<HTMLDivElement>(null)
  const [mounted, setMounted] = React.useState(false)

  React.useEffect(() => {
    setMounted(true)
  }, [])

  const handleMouseEnter = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      setPosition({
        x: rect.right + 8,
        y: rect.top + rect.height / 2,
      })
    }
    setIsVisible(true)
  }

  const handleMouseLeave = () => {
    setIsVisible(false)
  }

  const tooltip =
    isVisible && mounted ? (
      <div
        className={cn(
          'fixed -translate-y-1/2 transform',
          'z-[999999] w-72 rounded-md border bg-white px-3 py-2 text-sm shadow-xl',
          'pointer-events-none whitespace-normal',
          className,
        )}
        style={{
          left: position.x,
          top: position.y,
        }}
      >
        {content}
      </div>
    ) : null

  return (
    <>
      <div
        ref={triggerRef}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className="inline-block"
      >
        {children}
      </div>
      {mounted && tooltip && createPortal(tooltip, document.body)}
    </>
  )
}

// Keep these exports for backward compatibility but they won't be used
export const TooltipProvider = ({
  children,
}: {
  children: React.ReactNode
}) => <>{children}</>
export const Tooltip = ({ children }: { children: React.ReactNode }) => (
  <>{children}</>
)
export const TooltipTrigger = ({ children }: { children: React.ReactNode }) => (
  <>{children}</>
)
export const TooltipContent = ({ children }: { children: React.ReactNode }) => (
  <>{children}</>
)
