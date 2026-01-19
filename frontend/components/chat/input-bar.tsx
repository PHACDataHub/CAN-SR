'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Mic, StopCircle, Globe } from 'lucide-react'
import type { UseChatHelpers } from '@ai-sdk/react'
import { useStreamingWebSearch } from './streaming-web-search'

interface InputBarProps {
  chat: UseChatHelpers
  isRecording: boolean
  toggleRecording: () => void
}

export function InputBar({
  chat,
  isRecording,
  toggleRecording,
}: InputBarProps) {
  const { input, handleInputChange, isLoading, handleSubmit } = chat
  const [isMicHovered, setIsMicHovered] = useState(false)
  const [isWebHovered, setIsWebHovered] = useState(false)
  const [isWebSearching, setIsWebSearching] = useState(false)
  const [isWebActive, setIsWebActive] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { isLoading: isStreamingSearching, startStreamingSearch } =
    useStreamingWebSearch()

  // Auto-resize textarea as content grows
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
    }
  }, [input])

  // Custom submit handler that checks web search toggle
  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!input.trim()) return

    if (isWebActive) {
      console.log('🌐 Web search is active - skipping local RAG search')
      setIsWebSearching(true)
      let searchCompleted = false

      const setMessages = (chat as any).setMessages as
        | ((updater: any) => void)
        | undefined
      const userMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: input.trim(),
      }
      const assistantId = `assistant-${Date.now()}`

      if (typeof setMessages === 'function') {
        setMessages((prev: any[]) => [
          ...prev,
          userMessage,
          {
            id: assistantId,
            role: 'assistant',
            content: '',
            isStreaming: true,
            timelineEvents: [],
          },
        ])
      }

      const handleInputChange = (chat as any).handleInputChange
      if (typeof handleInputChange === 'function') {
        handleInputChange({ target: { value: '' } })
      }

      startStreamingSearch(
        input.trim(),
        (result) => {
          const finalAnswer = result?.final_answer || 'Web search completed.'
          const sources = Array.isArray(result?.sources) ? result.sources : []

          const searchQueries = result?.debug_info?.search_queries_used || []
          const groundingSupports = result?.debug_info?.grounding_supports || []
          const totalGroundedSegments =
            result?.debug_info?.total_grounded_segments || 0

          // Convert web search sources to Citation format
          const formattedCitations =
            sources.length > 0
              ? sources.map((source: any, index: number) => ({
                  id: index + 1,
                  filename: source.title || `Web Source ${index + 1}`,
                  content: source.snippet || '',
                  source_type: source.source_type || 'google',
                  title: source.title,
                  url: source.url,
                  snippet: source.snippet,
                  // Add rich grounding data
                  supported_segments_count:
                    source.supported_segments_count || 0,
                  supported_segments: source.supported_segments || [],
                  chunk_index: source.chunk_index,
                }))
              : []

          // Add search queries and grounding metadata to citations if available
          if (
            (searchQueries.length > 0 || groundingSupports.length > 0) &&
            formattedCitations.length > 0
          ) {
            formattedCitations[0].metadata = {
              ...formattedCitations[0].metadata,
              search_queries_used: searchQueries,
              grounding_supports: groundingSupports,
              total_grounded_segments: totalGroundedSegments,
            }
          }

          // Update final message with citations - USE requestAnimationFrame to ensure this runs after timeline updates
          searchCompleted = true // Mark search as completed
          if (typeof setMessages === 'function') {
            console.log('💾 FINAL: Setting storedCitations on message:', {
              assistantId,
              citationsCount: formattedCitations.length,
              firstCitation: formattedCitations[0],
            })

            // Use requestAnimationFrame to ensure this update happens after all pending updates
            requestAnimationFrame(() => {
              setMessages((prev: any[]) =>
                prev.map((msg: any) => {
                  if (msg.id === assistantId) {
                    const updatedMsg = {
                      ...msg,
                      content: finalAnswer, // Use clean final answer without inline sources
                      isStreaming: false,
                      storedCitations: formattedCitations, // Store formatted citations for Sources button
                      searchCompleted: true, // Mark this message as having completed search
                    }
                    console.log(
                      '✅ FINAL: Updated message with storedCitations via RAF:',
                      {
                        messageId: updatedMsg.id,
                        citationsCount: updatedMsg.storedCitations?.length || 0,
                        searchCompleted: true,
                      },
                    )
                    return updatedMsg
                  } else {
                    return msg
                  }
                }),
              )
            })
          }
          setIsWebSearching(false)
        },
        (error) => {
          // On error
          if (typeof setMessages === 'function') {
            setMessages((prev: any[]) =>
              prev.map((msg: any) =>
                msg.id === assistantId
                  ? {
                      ...msg,
                      content: `Web search failed: ${error}`,
                      isStreaming: false,
                    }
                  : msg,
              ),
            )
          }
          setIsWebSearching(false)
        },
        (timelineEvents) => {
          // Real-time timeline updates during streaming (deferred to avoid React render cycle issues)
          if (typeof setMessages === 'function' && !searchCompleted) {
            setTimeout(() => {
              // Double-check searchCompleted flag in case it changed
              if (searchCompleted) {
                console.log('🚫 Search completed - stopping timeline updates')
                return
              }

              setMessages((prev: any[]) =>
                prev.map((msg: any) => {
                  if (msg.id === assistantId) {
                    // Don't update if search is marked as completed
                    if (
                      msg.searchCompleted ||
                      (msg.storedCitations &&
                        msg.storedCitations.length > 0 &&
                        !msg.isStreaming)
                    ) {
                      console.log(
                        '🚫 Skipping timeline update - search complete',
                      )
                      return msg // Return unchanged
                    }

                    const preservedCitations = msg.storedCitations
                    const updatedMsg = {
                      ...msg,
                      timelineEvents,
                    }

                    // Always preserve storedCitations if they exist
                    if (preservedCitations && preservedCitations.length > 0) {
                      updatedMsg.storedCitations = preservedCitations
                      console.log(
                        '🔄 Timeline update preserving citations:',
                        preservedCitations.length,
                      )
                    }

                    return updatedMsg
                  } else {
                    return msg
                  }
                }),
              )
            }, 0)
          }
        },
        (streamingContent) => {
          // Real-time answer chunk updates during streaming (throttled for smoothness)
          if (typeof setMessages === 'function') {
            setMessages((prev: any[]) =>
              prev.map((msg: any) => {
                if (msg.id === assistantId) {
                  const preservedCitations = msg.storedCitations
                  const updatedMsg = {
                    ...msg,
                    content: streamingContent,
                  }

                  // Always preserve storedCitations if they exist
                  if (preservedCitations && preservedCitations.length > 0) {
                    updatedMsg.storedCitations = preservedCitations
                    console.log(
                      '📝 Streaming update preserving citations:',
                      preservedCitations.length,
                    )
                  }

                  return updatedMsg
                } else {
                  return msg
                }
              }),
            )
          }
        },
      )
    } else {
      console.log('🔍 Local RAG search triggered - web search is disabled')
      // Use regular RAG chat when web search is disabled
      handleSubmit(e)
    }
  }

  return (
    <div className="w-full">
      <form onSubmit={handleFormSubmit} className="w-full">
        <div className="relative z-20">
          <div className="flex w-full flex-col rounded-2xl border border-gray-200 bg-white shadow-lg transition-all duration-200 focus-within:border-gray-400 focus-within:ring-1 focus-within:ring-gray-400">
            {/* Row 1: Input + Mic */}
            <div className="flex items-center">
              <div className="flex-grow">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => handleInputChange(e)}
                  placeholder={
                    isWebActive
                      ? "Ask me anything - I'll search the web quickly for you..."
                      : 'Ask about documentation, research papers, or scientific concepts...'
                  }
                  rows={1}
                  className="w-full resize-none border-0 bg-transparent px-3 py-4 focus:ring-0 focus:outline-none"
                  style={{
                    minHeight: '56px',
                    maxHeight: '200px',
                    lineHeight: '1.5',
                    display: 'block',
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      if (input.trim()) {
                        handleFormSubmit(e)
                      }
                    }
                  }}
                />
              </div>
              <div className="flex flex-shrink-0 items-center gap-1.5 px-3">
                <button
                  type="button"
                  onClick={toggleRecording}
                  onMouseEnter={() => setIsMicHovered(true)}
                  onMouseLeave={() => setIsMicHovered(false)}
                  className={`flex h-10 w-10 items-center justify-center rounded-full transition-all duration-200 hover:bg-gray-100 focus:outline-none ${isRecording ? 'bg-red-50 text-red-500' : 'text-gray-500'}`}
                >
                  <div className="relative">
                    {isRecording ? (
                      <StopCircle className="h-6 w-6 animate-pulse" />
                    ) : (
                      <Mic className="h-6 w-6" />
                    )}
                    <span
                      className={`absolute -bottom-8 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-gray-800 px-2 py-1 text-xs whitespace-nowrap text-white opacity-0 transition-opacity ${isMicHovered ? 'opacity-80' : ''}`}
                    >
                      {isRecording ? 'Stop recording' : 'Start recording'}
                    </span>
                    {isRecording && (
                      <span className="absolute -top-1 -right-1 flex h-3 w-3">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75"></span>
                        <span className="relative inline-flex h-3 w-3 rounded-full bg-red-500"></span>
                      </span>
                    )}
                  </div>
                </button>
              </div>
            </div>

            {/* Divider */}
            <div className="h-px w-full bg-gray-100" />

            {/* Row 2: Search web (left) + Send (right) */}
            <div className="flex items-center justify-between px-2 py-2">
              <div className="flex items-center">
                <button
                  type="button"
                  aria-label="Toggle web search mode"
                  disabled={isLoading}
                  onClick={() => {
                    // Toggle the web search state
                    setIsWebActive(!isWebActive)
                  }}
                  onMouseEnter={() => setIsWebHovered(true)}
                  className={`group flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors disabled:opacity-60 ${
                    isWebActive
                      ? 'border-blue-200 bg-blue-50 text-blue-600'
                      : 'border-gray-200 bg-gray-50 text-gray-700 hover:bg-gray-100'
                  } ${isWebHovered ? (isWebActive ? 'ring-1 ring-blue-200' : 'ring-1 ring-gray-300') : ''} focus-visible:ring-1 focus-visible:ring-blue-200 active:border-blue-200 active:bg-blue-50 active:text-blue-600`}
                  aria-pressed={isWebActive}
                >
                  <Globe className="h-4 w-4" />
                  <span>Search web</span>
                </button>
              </div>
              <div className="flex items-center pr-1">
                <button
                  type="submit"
                  disabled={
                    isLoading ||
                    isWebSearching ||
                    isStreamingSearching ||
                    !input.trim()
                  }
                  className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-700 text-white transition-all duration-200 hover:bg-gray-800 disabled:bg-gray-300 disabled:text-gray-500 disabled:hover:bg-gray-300"
                >
                  <Send className="h-5 w-5" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </form>
    </div>
  )
}
