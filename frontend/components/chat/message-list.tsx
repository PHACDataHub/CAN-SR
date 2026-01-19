'use client'

import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Globe,
  Copy,
  ThumbsUp,
  ThumbsDown,
  RefreshCw,
  FileText,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { ActivityTimeline } from './activity-timeline'
import { Citation } from './types'

// Simple Message interface based on usage patterns
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
}

// Extended Message interface for web search features
interface ExtendedMessage extends Message {
  timelineEvents?: ProcessedEvent[]
  isStreaming?: boolean
}

// ProcessedEvent interface from activity-timeline
interface ProcessedEvent {
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

interface MessageListProps {
  messages: ExtendedMessage[]
  isLoading: boolean
  onRegenerate?: () => void
  onShowSources?: (sources: Citation[], messageId: string) => void
}

export function MessageList({
  messages,
  isLoading,
  onRegenerate,
  onShowSources,
}: MessageListProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [likedMessages, setLikedMessages] = useState<Set<string>>(new Set())
  const [dislikedMessages, setDislikedMessages] = useState<Set<string>>(
    new Set(),
  )
  const lastMessageRef = useRef<HTMLDivElement>(null)
  const [lastMessageId, setLastMessageId] = useState<string | null>(null)
  const [isNewMessage, setIsNewMessage] = useState(false)

  // Track when a new message is added or updated
  useEffect(() => {
    if (messages.length > 0) {
      const lastMsg = messages[messages.length - 1]
      if (lastMsg.id !== lastMessageId) {
        setLastMessageId(lastMsg.id)
        setIsNewMessage(true)
        // Reset the new message flag after a brief delay
        setTimeout(() => setIsNewMessage(false), 100)
      }
    }
  }, [messages, lastMessageId])

  // Scroll to the latest message
  useEffect(() => {
    if (lastMessageRef.current && (isLoading || isNewMessage)) {
      // Add bottom offset so content doesn't hide behind the input bar
      lastMessageRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'end',
      })
      window.scrollBy({ top: 120 })
    }
  }, [isLoading, isNewMessage, messages])

  const handleCopy = async (content: string, messageId: string) => {
    await navigator.clipboard.writeText(content)
    setCopiedId(messageId)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const handleLike = (messageId: string) => {
    setLikedMessages((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(messageId)) {
        newSet.delete(messageId)
      } else {
        newSet.add(messageId)
        setDislikedMessages((prev) => {
          const newDisliked = new Set(prev)
          newDisliked.delete(messageId)
          return newDisliked
        })
      }
      return newSet
    })
  }

  const handleDislike = (messageId: string) => {
    setDislikedMessages((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(messageId)) {
        newSet.delete(messageId)
      } else {
        newSet.add(messageId)
        setLikedMessages((prev) => {
          const newLiked = new Set(prev)
          newLiked.delete(messageId)
          return newLiked
        })
      }
      return newSet
    })
  }

  // Simple message processing with citation extraction
  const processedMessages = useMemo(() => {
    return messages.map((message, index) => {
      const isUser = message.role === 'user'
      const isLastMessage = index === messages.length - 1
      const isStreaming =
        message.isStreaming || (isLastMessage && isLoading && !isUser)

      let cleanContent = message.content || ''
      let storedCitations = (message as any).storedCitations || []

      // Extract citations from the new format if they exist - only for completed messages
      if (
        !isUser &&
        !isStreaming &&
        message.content &&
        message.content.includes('CITATIONS:')
      ) {
        const citationStart = message.content.indexOf('CITATIONS:')
        if (citationStart !== -1) {
          // Split content from citations
          cleanContent = message.content.substring(0, citationStart).trim()

          try {
            const citationJson = message.content.substring(citationStart + 10) // Remove "CITATIONS:"
            const metadataStart = citationJson.indexOf('\n\nMETADATA:')
            const citationData =
              metadataStart !== -1
                ? citationJson.substring(0, metadataStart)
                : citationJson

            // Check if JSON appears to be complete (ends with })
            if (!citationData.trim().endsWith('}')) {
              console.warn('Citation JSON appears incomplete, skipping parse')
              // Skip parsing but continue processing the message
            } else {
              const parsedCitations = JSON.parse(citationData)
              if (parsedCitations.citations) {
                storedCitations = parsedCitations.citations
              }
            }
          } catch (error) {
            console.error('Error parsing citations:', error)
            console.error(
              'Citation data length:',
              message.content.substring(citationStart + 10).length,
            )
            console.error(
              'Citation data end preview:',
              message.content.substring(message.content.length - 100),
            )
            // Don't throw the error, just log it and continue without citations
          }
        }
      }

      return {
        ...message,
        content: cleanContent, // Use cleaned content without citation data
        isUser,
        isLastMessage,
        isStreaming,
        storedCitations,
        timelineEvents: message.timelineEvents || [],
      }
    })
  }, [messages, isLoading])

  // Handle citation button clicks
  useEffect(() => {
    const handleCitationClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement
      if (target.classList.contains('citation-button')) {
        const citationIndex = parseInt(target.dataset.citationIndex || '0')
        const messageId = target.dataset.messageId

        if (messageId && onShowSources) {
          // Find the message and its citations
          const message = processedMessages.find((m) => m.id === messageId)
          if (
            message &&
            message.storedCitations &&
            message.storedCitations.length > 0
          ) {
            // Open citation sidebar and highlight the specific citation
            onShowSources(message.storedCitations, messageId)

            // Optional: Add highlight effect to the clicked citation
            setTimeout(() => {
              const citationElement = document.querySelector(
                `[data-citation-index="${citationIndex}"]`,
              )
              if (citationElement) {
                citationElement.classList.add('citation-highlighted')
                setTimeout(() => {
                  citationElement.classList.remove('citation-highlighted')
                }, 2000)
              }
            }, 100)
          }
        }
      }
    }

    document.addEventListener('click', handleCitationClick)
    return () => document.removeEventListener('click', handleCitationClick)
  }, [processedMessages, onShowSources])

  // Scroll to the latest message
  useEffect(() => {
    if (lastMessageRef.current && (isLoading || isNewMessage)) {
      lastMessageRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [isLoading, isNewMessage, messages])

  if (messages.length === 0 && !isLoading) {
    return (
      <div
        className="pointer-events-none flex flex-col items-center text-center"
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          marginLeft: '160px',
          zIndex: 5,
        }}
      >
        <h3 className="mb-4 text-3xl font-medium text-gray-900">
          How can I help you today?
        </h3>
        <p className="max-w-lg text-lg text-gray-500">
          Ask me about scientific concepts, research papers, or any questions
          you have.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6 py-4">
      {processedMessages.map((message) => {
        return (
          <div
            key={message.id}
            className={`flex ${message.isUser ? 'justify-end' : 'justify-start'}`}
            ref={message.isLastMessage ? lastMessageRef : undefined}
          >
            {message.isUser ? (
              <div className="flex max-w-[85%] items-start gap-3">
                <div className="rounded-2xl bg-gray-700 px-4 py-3 text-white">
                  <div className="whitespace-pre-wrap text-white">
                    {message.content}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex w-full flex-col">
                <div className="w-full">
                  {/* Minimal thinking process for agentic search - outside grey background */}
                  {(message.isStreaming ||
                    (message.timelineEvents &&
                      message.timelineEvents.length > 0)) && (
                    <div className="mb-3">
                      <ActivityTimeline
                        processedEvents={message.timelineEvents || []}
                        isLoading={message.isStreaming || false}
                      />
                    </div>
                  )}

                  {/* Grey background only for actual response content */}
                  {message.content && (
                    <div
                      className={`w-full rounded-2xl bg-gray-100 px-4 py-3 text-gray-800 ${message.isStreaming ? 'streaming-content' : ''}`}
                    >
                      <div
                        className={`transition-all duration-300 ease-in-out ${!message.isStreaming ? 'animate-fadeIn' : 'animate-in slide-in-from-bottom-2'}`}
                      >
                        {/* Response header */}
                        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-700 transition-all duration-200">
                          <Globe
                            className={`h-4 w-4 transition-colors duration-200 ${message.timelineEvents && message.timelineEvents.length > 0 ? 'text-blue-500' : 'text-gray-500'}`}
                          />
                          <span className="transition-all duration-200">
                            {message.timelineEvents &&
                            message.timelineEvents.length > 0
                              ? 'Web Research Response'
                              : message.isStreaming
                                ? 'AI Responding...'
                                : 'Response'}
                          </span>
                          {message.isStreaming && (
                            <div className="ml-2 flex space-x-1">
                              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500"></div>
                              <div
                                className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500"
                                style={{ animationDelay: '0.2s' }}
                              ></div>
                              <div
                                className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500"
                                style={{ animationDelay: '0.4s' }}
                              ></div>
                            </div>
                          )}
                        </div>

                        {/* Text display with markdown rendering for web search responses */}
                        <div className="leading-relaxed text-gray-800">
                          {(() => {
                            const content = message.content || ''

                            // If this is a web search response, render as markdown
                            if (
                              message.timelineEvents &&
                              message.timelineEvents.length > 0
                            ) {
                              return (
                                <div className="markdown">
                                  <ReactMarkdown
                                    remarkPlugins={[remarkGfm, remarkMath]}
                                    components={{
                                      // Custom component for citation links
                                      a: ({ href, children, ...props }) => {
                                        // Check if this is a citation link [1](url)
                                        if (
                                          href &&
                                          children &&
                                          Array.isArray(children) &&
                                          children[0] &&
                                          typeof children[0] === 'string' &&
                                          children[0].match(/^\[\d+\]$/)
                                        ) {
                                          return (
                                            <a
                                              {...props}
                                              href={href}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              className="text-blue-600 underline decoration-1 underline-offset-2 transition-all duration-150 hover:text-blue-800 hover:decoration-2"
                                            >
                                              {children}
                                            </a>
                                          )
                                        }
                                        // Regular links
                                        return (
                                          <a
                                            {...props}
                                            href={href}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="text-blue-600 underline decoration-1 underline-offset-2 transition-all duration-150 hover:text-blue-800 hover:decoration-2"
                                          >
                                            {children}
                                          </a>
                                        )
                                      },
                                      // Custom component for code blocks
                                      code: ({
                                        className,
                                        children,
                                        ...props
                                      }) => {
                                        const isInline =
                                          !className ||
                                          !className.includes('language-')
                                        if (isInline) {
                                          return (
                                            <code
                                              {...props}
                                              className="rounded bg-gray-100 px-1 py-0.5 font-mono text-sm text-gray-800"
                                            >
                                              {children}
                                            </code>
                                          )
                                        }
                                        return (
                                          <code
                                            {...props}
                                            className="block overflow-x-auto rounded bg-gray-100 p-3 font-mono text-sm text-gray-800"
                                          >
                                            {children}
                                          </code>
                                        )
                                      },
                                    }}
                                  >
                                    {content}
                                  </ReactMarkdown>
                                </div>
                              )
                            }

                            // For non-web search responses, also render as markdown
                            return (
                              <div className="markdown">
                                <ReactMarkdown
                                  remarkPlugins={[remarkGfm, remarkMath]}
                                  components={{
                                    // Custom component for links
                                    a: ({ href, children, ...props }) => (
                                      <a
                                        {...props}
                                        href={href}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-blue-600 underline decoration-1 underline-offset-2 transition-all duration-150 hover:text-blue-800 hover:decoration-2"
                                      >
                                        {children}
                                      </a>
                                    ),
                                    // Custom component for code blocks
                                    code: ({
                                      className,
                                      children,
                                      ...props
                                    }) => {
                                      const isInline =
                                        !className ||
                                        !className.includes('language-')
                                      if (isInline) {
                                        return (
                                          <code
                                            {...props}
                                            className="rounded bg-gray-100 px-1 py-0.5 font-mono text-sm text-gray-800"
                                          >
                                            {children}
                                          </code>
                                        )
                                      }
                                      return (
                                        <code
                                          {...props}
                                          className="block overflow-x-auto rounded bg-gray-100 p-3 font-mono text-sm text-gray-800"
                                        >
                                          {children}
                                        </code>
                                      )
                                    },
                                  }}
                                >
                                  {content}
                                </ReactMarkdown>
                              </div>
                            )
                          })()}

                          {/* Typing cursor for streaming content */}
                          {message.isStreaming && message.content && (
                            <span className="typing-cursor ml-1 inline-block h-5 w-0.5 rounded-full bg-blue-500 shadow-sm"></span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Action buttons - only show for completed messages */}
                  {!message.isStreaming && (
                    <div className="mt-1 flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                        onClick={() => {
                          if (message.content) {
                            handleCopy(message.content, message.id)
                          }
                        }}
                      >
                        <Copy className="mr-1 h-4 w-4" />
                        {copiedId === message.id ? 'Copied!' : 'Copy'}
                      </Button>

                      {message.isLastMessage && onRegenerate && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 px-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                          onClick={onRegenerate}
                        >
                          <RefreshCw className="mr-1 h-4 w-4" />
                          Regenerate
                        </Button>
                      )}

                      {message.storedCitations &&
                        message.storedCitations.length > 0 &&
                        onShowSources && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 px-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                            onClick={() =>
                              onShowSources(message.storedCitations, message.id)
                            }
                          >
                            <FileText className="mr-1 h-4 w-4" />
                            Sources ({message.storedCitations.length})
                          </Button>
                        )}

                      <div className="ml-auto flex">
                        <Button
                          variant="ghost"
                          size="sm"
                          className={`h-8 w-8 rounded-full p-0 ${likedMessages.has(message.id) ? 'bg-green-50 text-green-600' : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'}`}
                          onClick={() => handleLike(message.id)}
                        >
                          <ThumbsUp className="h-4 w-4" />
                        </Button>

                        <Button
                          variant="ghost"
                          size="sm"
                          className={`h-8 w-8 rounded-full p-0 ${dislikedMessages.has(message.id) ? 'bg-red-50 text-red-600' : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'}`}
                          onClick={() => handleDislike(message.id)}
                        >
                          <ThumbsDown className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}

      {/* Clean, minimal thinking indicator - only show if no messages or the last message is from user */}
      {isLoading &&
        (!messages.length || messages[messages.length - 1].role === 'user') && (
          <div className="flex w-full justify-start">
            <div className="flex items-center rounded-2xl bg-gray-100 px-4 py-3">
              <div className="thinking-dots">
                <span className="thinking-dot"></span>
                <span className="thinking-dot"></span>
                <span className="thinking-dot"></span>
              </div>
            </div>
          </div>
        )}

      <style jsx global>{`
        .thinking-dots {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .thinking-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background-color: #d1d5db;
          opacity: 0.8;
        }

        .thinking-dot:nth-child(1) {
          animation: pulse 1.5s infinite;
        }

        .thinking-dot:nth-child(2) {
          animation: pulse 1.5s infinite 0.3s;
        }

        .thinking-dot:nth-child(3) {
          animation: pulse 1.5s infinite 0.6s;
        }

        @keyframes pulse {
          0%,
          100% {
            opacity: 0.4;
            transform: scale(0.8);
          }
          50% {
            opacity: 1;
            transform: scale(1);
          }
        }

        .streaming-content {
          position: relative;
        }

        /* Modern progress indicators */
        .progress-dots {
          animation: fadeInText 0.3s ease-in;
        }

        @keyframes fadeInText {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }

        /* Smooth text transitions */
        .thinking-text {
          transition: all 0.3s ease-in-out;
        }

        /* Smooth fade in animation for response */
        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .animate-fadeIn {
          animation: fadeIn 0.6s ease-out;
        }

        /* Smooth streaming text animation */
        @keyframes typeIn {
          from {
            opacity: 0;
            transform: translateY(2px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        /* Improved bounce animation for progress dots */
        @keyframes smoothBounce {
          0%,
          100% {
            transform: translateY(0);
            opacity: 0.7;
          }
          50% {
            transform: translateY(-8px);
            opacity: 1;
          }
        }

        .progress-dots .animate-bounce {
          animation: smoothBounce 1.2s ease-in-out infinite;
        }

        /* Smooth cursor blink */
        @keyframes blink {
          0%,
          50% {
            opacity: 1;
          }
          51%,
          100% {
            opacity: 0.3;
          }
        }

        .typing-cursor {
          animation: blink 1.2s ease-in-out infinite;
        }

        /* Citation button styles */
        .citation-button {
          font-size: 0.75rem;
          line-height: 1;
          margin-left: 0.125rem;
          transition: all 0.2s ease;
        }

        .citation-button:hover {
          transform: scale(1.1);
          box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
        }

        .citation-highlighted {
          background-color: #fbbf24 !important;
          color: #92400e !important;
          animation: citationPulse 0.6s ease-in-out;
        }

        @keyframes citationPulse {
          0% {
            transform: scale(1);
          }
          50% {
            transform: scale(1.2);
          }
          100% {
            transform: scale(1);
          }
        }
      `}</style>
    </div>
  )
}
