import { useEffect, useState } from 'react'

export interface ProcessedEvent {
  title: string
  data: any
  timestamp?: string
  type?:
    | 'thinking'
    | 'research'
    | 'reflection'
    | 'synthesis'
    | 'complete'
    | 'error'
}

interface ActivityTimelineProps {
  processedEvents: ProcessedEvent[]
  isLoading: boolean
}

export function ActivityTimeline({
  processedEvents,
  isLoading,
}: ActivityTimelineProps) {
  const [isTimelineCollapsed, setIsTimelineCollapsed] = useState<boolean>(true) // Default to collapsed for minimal view

  useEffect(() => {
    // Keep collapsed by default for minimal view
    if (!isLoading && processedEvents.length !== 0) {
      // Don't auto-expand, keep minimal
    }
  }, [isLoading, processedEvents])

  // Check if research is actually complete based on event content
  const isResearchComplete = () => {
    if (processedEvents.length > 0) {
      const lastEvent = processedEvents[processedEvents.length - 1]
      const title = lastEvent.title.toLowerCase()

      // More robust completion detection
      const isCompleteByTitle =
        title.includes('complete') ||
        title.includes('finished') ||
        title.includes('done') ||
        (title.includes('synthesis') && !isLoading)

      const isCompleteByState = !isLoading && processedEvents.length > 0

      const isComplete = isCompleteByTitle || isCompleteByState

      // Debug logging - only for recent events
      if (processedEvents.length > 10) {
        console.log('🟢 Research completion check:', {
          lastEventTitle: lastEvent.title,
          isLoading,
          isComplete,
          shouldShowGreenDots: isComplete,
        })
      }

      return isComplete
    }
    return false
  }

  // Get current step for minimal display with main action and sub-details
  const getCurrentStepDetails = () => {
    if (isLoading && processedEvents.length === 0) {
      return { main: 'Starting research', sub: null }
    }
    if (processedEvents.length > 0) {
      const lastEvent = processedEvents[processedEvents.length - 1]
      const main = lastEvent.title
      let sub = null

      // Extract sub-details from event data
      if (lastEvent.data) {
        if (typeof lastEvent.data === 'string') {
          const lines = lastEvent.data.split('\n')
          // Take the first meaningful line as sub-detail
          for (const line of lines) {
            const trimmed = line.trim()
            if (trimmed && !trimmed.startsWith('•') && trimmed.length > 3) {
              sub = trimmed
              break
            }
          }
          // Display full text without truncation
        } else if (typeof lastEvent.data === 'object') {
          // Handle structured data
          if (lastEvent.data.queries && Array.isArray(lastEvent.data.queries)) {
            sub = `Generating ${lastEvent.data.queries.length} search queries...`
          } else if (lastEvent.data.sources_found) {
            sub = `Found ${lastEvent.data.sources_found} sources`
          } else if (lastEvent.data.status) {
            sub = lastEvent.data.status
          }
        }
      }

      return { main, sub }
    }
    return { main: null, sub: null }
  }

  const { main, sub } = getCurrentStepDetails()

  // Don't show anything if no activity
  if (!isLoading && processedEvents.length === 0) {
    return null
  }

  return (
    <div className="mb-4">
      {/* Cursor-style thinking indicator */}
      {isTimelineCollapsed && main && (
        <div className="flex items-start gap-3 py-2">
          {/* Cursor-style dots - only show when actively thinking */}
          <div className="mt-0.5 flex-shrink-0">
            {(() => {
              const showGreenDots = isResearchComplete()

              return showGreenDots ? (
                // No dots when complete - just empty space for alignment
                <div className="h-1.5 w-1.5"></div>
              ) : (
                <div className="cursor-thinking-dots">
                  <div className="cursor-thinking-dot"></div>
                  <div className="cursor-thinking-dot"></div>
                  <div className="cursor-thinking-dot"></div>
                </div>
              )
            })()}
          </div>

          {/* Current step with main action and sub-details */}
          <div className="min-w-0 flex-1">
            {/* Main action in normal text */}
            <div className="text-sm leading-snug font-medium text-gray-800">
              {main}
            </div>

            {/* Sub-details in thinner font */}
            {sub && (
              <div className="mt-1 text-xs leading-relaxed font-normal break-words text-gray-600">
                {sub}
              </div>
            )}
          </div>

          {/* Show steps button - with proper spacing */}
          {processedEvents.length > 1 && (
            <button
              onClick={() => setIsTimelineCollapsed(false)}
              className="ml-3 flex-shrink-0 text-xs font-medium text-gray-500 underline hover:text-gray-700"
            >
              Show {processedEvents.length} steps
            </button>
          )}
        </div>
      )}

      {/* Expanded Timeline*/}
      {!isTimelineCollapsed && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-800">
                Research Steps
              </span>
              <span className="rounded-full bg-gray-200 px-2 py-1 text-xs font-medium text-gray-600">
                {processedEvents.length}
              </span>
            </div>
            <button
              onClick={() => setIsTimelineCollapsed(true)}
              className="text-xs font-medium text-gray-500 underline hover:text-gray-700"
            >
              Collapse
            </button>
          </div>

          <div className="max-h-64 space-y-2 overflow-y-auto">
            {processedEvents.map((eventItem, index) => (
              <div key={index} className="flex items-start gap-3 py-1.5">
                <div className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-gray-400"></div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm leading-snug font-medium text-gray-800">
                    {eventItem.title}
                  </p>
                  {eventItem.data && typeof eventItem.data === 'string' && (
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-600">
                      {eventItem.data}
                    </p>
                  )}
                </div>
              </div>
            ))}

            {/* Current Loading Step */}
            {isLoading && (
              <div className="flex items-start gap-3 py-1.5">
                <div className="thinking-dots-small mt-1.5">
                  <span className="thinking-dot-small"></span>
                  <span className="thinking-dot-small"></span>
                  <span className="thinking-dot-small"></span>
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-700">
                    Processing...
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <style jsx>{`
        .cursor-thinking-dots {
          display: flex;
          align-items: center;
          gap: 2px;
        }

        .cursor-thinking-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background-color: #9ca3af;
          animation: cursorPulse 1.5s ease-in-out infinite;
        }

        .cursor-thinking-dot:nth-child(1) {
          animation-delay: 0s;
        }
        .cursor-thinking-dot:nth-child(2) {
          animation-delay: 0.2s;
        }
        .cursor-thinking-dot:nth-child(3) {
          animation-delay: 0.4s;
        }

        .thinking-dots {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .thinking-dot {
          width: 4px;
          height: 4px;
          border-radius: 50%;
          background-color: #6b7280;
          animation: thinking 1.4s ease-in-out infinite both;
        }

        .thinking-dot:nth-child(1) {
          animation-delay: -0.32s;
        }
        .thinking-dot:nth-child(2) {
          animation-delay: -0.16s;
        }

        .thinking-dots-small {
          display: flex;
          align-items: center;
          gap: 2px;
        }

        .thinking-dot-small {
          width: 3px;
          height: 3px;
          border-radius: 50%;
          background-color: #9ca3af;
          animation: thinking 1.4s ease-in-out infinite both;
        }

        .thinking-dot-small:nth-child(1) {
          animation-delay: -0.32s;
        }
        .thinking-dot-small:nth-child(2) {
          animation-delay: -0.16s;
        }

        @keyframes cursorPulse {
          0%,
          100% {
            opacity: 0.4;
          }
          50% {
            opacity: 1;
          }
        }

        @keyframes thinking {
          0%,
          80%,
          100% {
            opacity: 0.3;
            transform: scale(0.8);
          }
          40% {
            opacity: 1;
            transform: scale(1);
          }
        }
      `}</style>
    </div>
  )
}
