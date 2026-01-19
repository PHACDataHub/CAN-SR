import { useState, useRef } from 'react'
import { ProcessedEvent } from './activity-timeline'
import { getAuthToken, getTokenType } from '@/lib/auth'

export function useStreamingWebSearch() {
  const [timelineEvents, setTimelineEvents] = useState<ProcessedEvent[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [streamingAnswer, setStreamingAnswer] = useState<string>('')
  const abortControllerRef = useRef<AbortController | null>(null)
  const updateTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  const processStreamEvent = (eventData: any): ProcessedEvent | null => {
    const eventType = eventData.event_type
    const data = eventData.data

    switch (eventType) {
      case 'generate_query':
        if (data.status === 'generating_queries') {
          return {
            title: 'Analyzing query',
            data: `Generating ${data.query_count} search queries...`,
          }
        } else if (data.status === 'queries_generated') {
          const queries = data.search_query || []
          const queriesDisplay =
            queries.length > 0
              ? queries
                  .map((q: string, i: number) => `${i + 1}. ${q}`)
                  .join('\n')
              : 'Queries ready'
          return {
            title: 'Search queries generated',
            data: `${queries.length} queries:\n${queriesDisplay}`,
          }
        }
        break

      case 'web_research':
        if (data.status === 'starting_research') {
          return {
            title: `Research iteration ${data.iteration}`,
            data: `Searching ${data.query_count} queries for comprehensive information`,
          }
        } else if (data.status === 'researching_query') {
          return {
            title: `Searching web`,
            data: `Query ${data.query_index}/${data.total_queries}: ${data.query}`,
          }
        } else if (data.status === 'query_completed') {
          const sourcesInfo =
            data.sources_found > 0
              ? `Found ${data.sources_found} sources`
              : 'No sources found'
          const totalSources = data.sources_gathered?.length || 0
          return {
            title: 'Sources collected',
            data: `${sourcesInfo} • Total: ${totalSources} sources`,
          }
        }
        break

      case 'reflection':
        if (data.status === 'analyzing_results') {
          return {
            title: 'Analyzing results',
            data: `Reviewing ${data.sources_gathered} sources from iteration ${data.iteration}`,
          }
        } else if (data.status === 'reflection_completed') {
          if (data.is_sufficient) {
            return {
              title: 'Analysis complete',
              data: 'Sufficient information gathered. Ready to synthesize answer.',
            }
          } else {
            const gap = data.knowledge_gap || 'Need more information'
            const followUpQueries = data.follow_up_queries || []
            const nextSteps =
              followUpQueries.length > 0
                ? `\nNext queries:\n${followUpQueries.map((q: string) => `• ${q}`).join('\n')}`
                : ''
            return {
              title: 'Knowledge gap identified',
              data: `${gap}${nextSteps}`,
            }
          }
        }
        break

      case 'answer_chunk':
        return null

      case 'finalize_answer':
        if (data.status === 'generating_final_answer') {
          return {
            title: 'Synthesizing answer',
            data: `Combining insights from ${data.total_sources} sources across ${data.iterations_completed} iterations`,
          }
        } else if (data.status === 'completed') {
          const timeDisplay = data.processing_time
            ? ` (${data.processing_time.toFixed(1)}s)`
            : ''
          return {
            title: 'Research complete',
            data: `Generated comprehensive answer using ${data.total_sources} sources across ${data.iterations_completed} iterations${timeDisplay}`,
          }
        }
        break

      case 'error':
        return {
          title: 'Error',
          data: data.error || 'An error occurred during research',
        }

      default:
        return null
    }

    return null
  }

  const startStreamingSearch = async (
    input: string,
    onComplete: (result: any) => void,
    onError: (error: string) => void,
    onTimelineUpdated?: (events: ProcessedEvent[]) => void,
    onAnswerChunk?: (chunk: string) => void,
  ) => {
    setIsLoading(true)
    setTimelineEvents([])
    setStreamingAnswer('')

    abortControllerRef.current = new AbortController()

    try {
      const token = getAuthToken()
      if (!token) {
        throw new Error(
          'Authentication required. Please log in to use agentic search.',
        )
      }

      const backendUrl = `${
        process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
      }/api/agents/agentic_search/research/stream`

      const tokenType = getTokenType()
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        Authorization: `${tokenType} ${token}`,
      }

      const response = await fetch(backendUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          query: input.trim(),
          agent_type: 'google',
          max_iterations: 2,
          include_citations: true,
          search_depth: 'standard',
        }),
        signal: abortControllerRef.current.signal,
      })

      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          throw new Error(
            'Authentication required. Please log in to use agentic search.',
          )
        }
        const errorText = await response.text()
        throw new Error(
          `HTTP ${response.status}: ${errorText || response.statusText}`,
        )
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body reader available')
      }

      const decoder = new TextDecoder()
      let buffer = ''
      let finalResult: any = null

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.trim() === '') continue
            if (!line.startsWith('data: ')) continue

            try {
              const eventData = JSON.parse(line.slice(6))

              if (
                eventData.event_type === 'answer_chunk' &&
                eventData.data.chunk
              ) {
                const chunk = eventData.data.chunk
                setStreamingAnswer((prev) => {
                  const newAnswer = prev + chunk
                  if (onAnswerChunk) {
                    if (updateTimeoutRef.current) {
                      clearTimeout(updateTimeoutRef.current)
                    }
                    updateTimeoutRef.current = setTimeout(() => {
                      onAnswerChunk(newAnswer)
                    }, 16)
                  }
                  return newAnswer
                })
              }

              const processedEvent = processStreamEvent(eventData)

              if (processedEvent) {
                setTimelineEvents((prev) => {
                  const newEvents = [...prev, processedEvent]
                  if (onTimelineUpdated) {
                    onTimelineUpdated(newEvents)
                  }
                  return newEvents
                })
              }

              if (
                eventData.event_type === 'finalize_answer' &&
                eventData.data.status === 'completed' &&
                eventData.data.response
              ) {
                finalResult = eventData.data.response
              } else if (eventData.event_type === 'error') {
                throw new Error(
                  eventData.data.error || 'Backend error occurred',
                )
              }
            } catch (e) {
              console.warn('Failed to parse SSE event:', line, e)
            }
          }
        }
      } finally {
        reader.releaseLock()
      }

      setIsLoading(false)

      if (finalResult) {
        onComplete(finalResult)
      } else {
        onError('Search completed but no final result received')
      }
    } catch (error: any) {
      setIsLoading(false)

      if (error.name === 'AbortError') {
        onError('Search was cancelled')
      } else {
        onError(error.message || 'Failed to perform streaming search')
      }
    }
  }

  const cancelSearch = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    if (updateTimeoutRef.current) {
      clearTimeout(updateTimeoutRef.current)
      updateTimeoutRef.current = null
    }
    setIsLoading(false)
    setStreamingAnswer('')
  }

  return {
    timelineEvents,
    isLoading,
    streamingAnswer,
    startStreamingSearch,
    cancelSearch,
  }
}
