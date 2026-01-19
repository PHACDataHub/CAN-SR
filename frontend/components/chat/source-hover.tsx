'use client'

import { useState, useRef, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { FileText, X } from 'lucide-react'
import type { Citation } from './types'

interface SourceHoverProps {
  source: Citation
  children: React.ReactNode
  zIndex?: number
}

export function SourceHover({
  source,
  children,
  zIndex = 50,
}: SourceHoverProps) {
  const [isVisible, setIsVisible] = useState(false)
  const [tooltipPosition, setTooltipPosition] = useState({ top: 0, left: 0 })
  const [tooltipWidth, setTooltipWidth] = useState(400) // Smaller default width
  const triggerRef = useRef<HTMLSpanElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const hoverTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  const formatScore = (score?: number) => {
    if (score === undefined) return 'N/A'
    return (score * 100).toFixed(1) + '%'
  }

  const truncateContent = (content: string, maxLength: number = 600) => {
    if (!content || content.length <= maxLength) return content
    return content.substring(0, maxLength) + '...'
  }

  const updateTooltipPosition = () => {
    if (!triggerRef.current) return

    const triggerRect = triggerRef.current.getBoundingClientRect()
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight

    // Make tooltip more compact
    const minPadding = 16 // Smaller padding from screen edges
    const maxTooltipWidth = Math.min(450, viewportWidth - minPadding * 2) // Smaller max width
    const calculatedWidth = Math.max(350, maxTooltipWidth) // Smaller minimum width
    const tooltipHeight = 400 // Slightly shorter for better positioning

    // Update tooltip width state
    setTooltipWidth(calculatedWidth)

    // Try to position to the right of the trigger first if there's space
    let left = triggerRect.right + 8
    let top = triggerRect.top - 10 // Slightly above the trigger for better alignment

    // If not enough space on right, try left
    if (left + calculatedWidth > viewportWidth - minPadding) {
      left = triggerRect.left - calculatedWidth - 8
    }

    // If not enough space on left either, position below or above
    if (left < minPadding) {
      left = Math.max(minPadding, triggerRect.left)
      top = triggerRect.bottom + 8

      // If not enough space below, position above
      if (top + tooltipHeight > viewportHeight - minPadding) {
        top = Math.max(minPadding, triggerRect.top - tooltipHeight - 8)
      }
    }

    // Final adjustment to ensure tooltip is within viewport
    if (top + tooltipHeight > viewportHeight - minPadding) {
      top = viewportHeight - tooltipHeight - minPadding
    }
    if (top < minPadding) {
      top = minPadding
    }

    setTooltipPosition({ top, left })
  }

  const handleMouseEnter = () => {
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current)
    }
    setIsVisible(true)
    setTimeout(updateTooltipPosition, 0)
  }

  const handleMouseLeave = () => {
    hoverTimeoutRef.current = setTimeout(() => {
      setIsVisible(false)
    }, 150)
  }

  const handleTooltipMouseEnter = () => {
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current)
    }
  }

  const handleTooltipMouseLeave = () => {
    setIsVisible(false)
  }

  const handleClose = () => {
    setIsVisible(false)
  }

  useEffect(() => {
    return () => {
      if (hoverTimeoutRef.current) {
        clearTimeout(hoverTimeoutRef.current)
      }
    }
  }, [])

  return (
    <>
      <span
        ref={triggerRef}
        className="mr-2 mb-2 inline-block cursor-pointer rounded-md border border-blue-200 px-2 py-1 text-sm font-medium text-blue-600 transition-all duration-200 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800 hover:shadow-sm"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {children}
      </span>

      {isVisible && (
        <div
          ref={tooltipRef}
          className="pointer-events-auto fixed overflow-hidden rounded-xl border border-gray-300 bg-white p-0 shadow-xl"
          style={{
            top: tooltipPosition.top,
            left: tooltipPosition.left,
            width: `${tooltipWidth}px`,
            maxHeight: '400px',
            zIndex: zIndex,
          }}
          onMouseEnter={handleTooltipMouseEnter}
          onMouseLeave={handleTooltipMouseLeave}
        >
          {/* Header with close button */}
          <div className="flex items-center justify-between border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50 px-3 py-2">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-blue-600" />
              <span className="text-sm font-semibold text-gray-900">
                Source Details
              </span>
              <Badge
                variant="secondary"
                className="ml-2 bg-blue-100 text-xs text-blue-700"
              >
                {formatScore(source.distance)}
              </Badge>
            </div>
            <button
              onClick={handleClose}
              className="text-gray-500 hover:text-gray-700 focus:outline-none"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div
            className="source-hover-content p-4"
            style={{ maxHeight: '350px' }}
          >
            {/* Document Info - More compact */}
            <div className="mb-3">
              <div className="mb-2">
                <label className="mb-1 block text-xs font-medium tracking-wide text-gray-500 uppercase">
                  Document
                </label>
                <p className="text-sm font-semibold break-words text-gray-900">
                  {source.filename}
                </p>
              </div>

              {/* Primary Metadata Grid - More compact */}
              <div className="mb-2 grid grid-cols-3 gap-2">
                {(source.source_type || source.metadata?.document_type) && (
                  <div>
                    <label className="text-xs font-medium tracking-wide text-gray-500 uppercase">
                      Type
                    </label>
                    <p className="text-sm font-medium text-gray-700">
                      {source.source_type === 'base' ||
                      source.metadata?.document_type === 'base'
                        ? 'Base Knowledge'
                        : 'User Document'}
                    </p>
                  </div>
                )}

                {source.metadata?.page_no && (
                  <div>
                    <label className="text-xs font-medium tracking-wide text-gray-500 uppercase">
                      Page
                    </label>
                    <p className="text-sm font-medium text-gray-700">
                      Page {source.metadata?.page_no}
                    </p>
                  </div>
                )}

                {source.chunk_index !== undefined && (
                  <div>
                    <label className="text-xs font-medium tracking-wide text-gray-500 uppercase">
                      Chunk
                    </label>
                    <p className="text-sm font-medium text-gray-700">
                      #{source.chunk_index}
                    </p>
                  </div>
                )}
              </div>

              {/* Document Structure - More compact */}
              {(source.metadata?.headings ||
                source.metadata?.document_title) && (
                <div className="mb-2 rounded-lg border border-blue-200 bg-blue-50 p-2">
                  {source.metadata?.document_title && (
                    <div className="mb-1">
                      <label className="text-xs font-medium tracking-wide text-blue-600 uppercase">
                        Document Title
                      </label>
                      <p className="text-sm font-medium text-blue-800">
                        {source.metadata?.document_title}
                      </p>
                    </div>
                  )}
                  {source.metadata?.headings && (
                    <div>
                      <label className="text-xs font-medium tracking-wide text-blue-600 uppercase">
                        Section Headings
                      </label>
                      <p className="text-sm text-blue-800">
                        {source.metadata?.headings}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Chunk Name - More compact */}
              {source.metadata?.chunk_name && (
                <div className="mb-2">
                  <label className="text-xs font-medium tracking-wide text-gray-500 uppercase">
                    Chunk Name
                  </label>
                  <p className="text-sm font-medium text-gray-700">
                    {source.metadata?.chunk_name}
                  </p>
                </div>
              )}
            </div>

            {/* Chunk Content - More compact */}
            <div className="mb-3">
              <div className="mb-2 flex items-center justify-between">
                <label className="text-xs font-medium tracking-wide text-gray-500 uppercase">
                  Content Preview
                </label>
                {source.content && (
                  <span className="text-xs text-gray-400">
                    {source.content.length} characters
                  </span>
                )}
              </div>
              <div className="source-hover-content max-h-48 rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm leading-relaxed whitespace-pre-wrap text-gray-800">
                  {truncateContent(source.content || 'No content available')}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// Component to display sources with hover details
interface SourceListProps {
  sources: Citation[]
}

export function SourceList({ sources }: SourceListProps) {
  // Remove filtering by score to show all sources
  const filteredSources = sources

  if (!filteredSources.length) return null

  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {filteredSources.map((source, index) => (
        <SourceHover
          key={`${source.id || index}-${source.filename || 'unknown'}-${source.chunk_index || 0}-${index}`}
          source={source}
          zIndex={100 - index} // Decreasing z-index for each source to prevent blocking
        >
          {source.filename.split('/').pop()?.split('.')[0] ||
            `Source ${index + 1}`}
        </SourceHover>
      ))}
    </div>
  )
}
