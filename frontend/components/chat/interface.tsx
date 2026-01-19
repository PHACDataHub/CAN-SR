'use client'

import type React from 'react'
import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  type SpeechRecognition,
  type SpeechRecognitionEvent,
  type SpeechRecognitionErrorEvent,
} from './types'
import { ScrollToBottomButton } from './scroll-button'
import { MessageList } from './message-list'
import { InputBar } from './input-bar'
import { CitationSidebar } from './citation-sidebar'
import type { ChatInterfaceProps } from './types'
import type { Citation } from './types'
import { FileText, X, Plus } from 'lucide-react'

export function ChatInterface({
  chat,
  isExitDialogOpen,
  setIsExitDialogOpen,
  selectedFiles,
  onClearSelectedFiles,
  onRemoveSelectedFile,
  onNavigateToFiles,
}: ChatInterfaceProps) {
  const { messages, isLoading, reload } = chat
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const [isRecording, setIsRecording] = useState(false)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const userStoppedRecording = useRef(false)
  const [showScrollButton, setShowScrollButton] = useState(false)
  const [isCitationSidebarOpen, setIsCitationSidebarOpen] = useState(false)
  const [citationSources, setCitationSources] = useState<Citation[]>([])
  const [citationMessageId, setCitationMessageId] = useState<string>('')
  const router = useRouter()

  const handleShowSources = (sources: Citation[], messageId: string) => {
    setCitationSources(sources)
    setCitationMessageId(messageId)
    setIsCitationSidebarOpen(true)
  }

  const handleCloseCitationSidebar = () => {
    setIsCitationSidebarOpen(false)
    setCitationSources([])
    setCitationMessageId('')
  }

  const scrollToBottom = (behavior: ScrollBehavior = 'auto') => {
    messagesContainerRef.current?.scrollTo({
      top: messagesContainerRef.current.scrollHeight,
      behavior,
    })
  }

  const handleScroll = () => {
    if (messagesContainerRef.current) {
      const container = messagesContainerRef.current
      const isScrolledUp =
        container.scrollHeight - container.scrollTop - container.clientHeight >
        100
      setShowScrollButton(isScrolledUp)
    }
  }

  // Auto-scroll for new messages and streaming
  useEffect(() => {
    scrollToBottom()
    if (isLoading) {
      const interval = setInterval(() => scrollToBottom(), 100)
      return () => clearInterval(interval)
    }
  }, [messages, isLoading])

  // Scroll event listener
  useEffect(() => {
    const container = messagesContainerRef.current
    if (container) {
      container.addEventListener('scroll', handleScroll)
      return () => container.removeEventListener('scroll', handleScroll)
    }
  }, [])

  // Initialize speech recognition
  useEffect(() => {
    if (typeof window !== 'undefined') {
      // Check if browser supports SpeechRecognition
      const SpeechRecognitionImpl =
        (window as any).SpeechRecognition ||
        (window as any).webkitSpeechRecognition
      if (SpeechRecognitionImpl) {
        recognitionRef.current = new SpeechRecognitionImpl()
        recognitionRef.current.continuous = true
        recognitionRef.current.interimResults = true

        recognitionRef.current.onresult = (event: SpeechRecognitionEvent) => {
          const transcript = Array.from(event.results)
            .map((result: any) => result[0])
            .map((result: any) => result.transcript)
            .join('')

          // Update the input with the transcript
          chat.setInput(transcript)
        }

        recognitionRef.current.onerror = (
          event: SpeechRecognitionErrorEvent,
        ) => {
          console.error('Speech recognition error', event.error)
          // Don't stop on 'no-speech' error, as user might just be pausing
          if (event.error !== 'no-speech') {
            setIsRecording(false)
          }
        }

        recognitionRef.current.onend = () => {
          // If the recording didn't stop due to a user action, restart it.
          if (!userStoppedRecording.current) {
            recognitionRef.current?.start()
          } else {
            setIsRecording(false)
            userStoppedRecording.current = false // Reset for next time
          }
        }
      }
    }

    // Cleanup
    return () => {
      if (recognitionRef.current) {
        userStoppedRecording.current = true
        recognitionRef.current.stop()
      }
    }
  }, [chat])

  const toggleRecording = () => {
    if (isRecording) {
      userStoppedRecording.current = true
      recognitionRef.current?.stop()
    } else {
      try {
        userStoppedRecording.current = false
        recognitionRef.current?.start()
        setIsRecording(true)
      } catch (error) {
        console.error('Speech recognition error:', error)
      }
    }
  }

  const handleLeave = () => router.push('/portal')
  const handleRegenerate = () => messages.length && reload()

  return (
    <>
      <div className="relative flex h-full flex-col bg-white">
        {/* Chat Messages Area */}
        <div
          className={`relative z-0 flex-1 overflow-y-auto px-4 pt-4 pb-4 transition-all duration-300 md:px-6 ${isCitationSidebarOpen ? 'mr-96' : ''}`}
          ref={messagesContainerRef}
        >
          <div className="mx-auto w-full max-w-4xl">
            <MessageList
              messages={messages}
              isLoading={isLoading}
              onRegenerate={handleRegenerate}
              onShowSources={handleShowSources}
            />
          </div>

          {/* Scroll to bottom button - positioned within chat area */}
          <ScrollToBottomButton
            visible={showScrollButton}
            onClick={() => scrollToBottom('smooth')}
          />
        </div>

        {/* Input Bar */}
        <div className="sticky bottom-0 z-20 bg-white">
          <div
            className={`transition-all duration-300 ${isCitationSidebarOpen ? 'mr-96' : ''}`}
          >
            <div className="mx-auto max-w-4xl px-4 pb-6">
              <div className="flex flex-col items-center">
                {/* Selected Files Indicator */}
                {selectedFiles && selectedFiles.length > 0 && (
                  <div className="mb-3 w-full">
                    <div className="flex items-center justify-between rounded-lg border border-slate-200/60 bg-slate-50/80 px-3 py-2 shadow-sm backdrop-blur-sm">
                      <div className="flex min-w-0 flex-1 items-center gap-2">
                        <FileText className="h-4 w-4 flex-shrink-0 text-slate-600" />
                        <span className="flex-shrink-0 text-sm font-medium text-slate-700">
                          Focused Search:
                        </span>
                        <div className="flex min-w-0 flex-1 items-center gap-1.5">
                          {/* Scrollable files container */}
                          <div className="scrollbar-hide flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto">
                            {selectedFiles.map((filename, index) => (
                              <div
                                key={index}
                                className="group inline-flex flex-shrink-0 items-center gap-1.5 rounded-md border border-slate-200/50 bg-white/80 px-2 py-0.5 text-xs text-slate-600 transition-colors hover:border-slate-300/60 hover:bg-white"
                                title={filename}
                              >
                                <div className="h-1.5 w-1.5 rounded-full bg-blue-500"></div>
                                <span className="cursor-default whitespace-nowrap">
                                  {filename.length > 20
                                    ? `${filename.substring(0, 20)}...`
                                    : filename}
                                </span>
                                {onRemoveSelectedFile && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      onRemoveSelectedFile(filename)
                                    }}
                                    className="ml-1 flex h-3.5 w-3.5 items-center justify-center rounded-sm text-slate-400 opacity-0 transition-all group-hover:opacity-100 hover:bg-slate-200 hover:text-slate-600"
                                    title={`Remove ${filename}`}
                                  >
                                    <X className="h-2.5 w-2.5" />
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                          {onNavigateToFiles && (
                            <button
                              onClick={onNavigateToFiles}
                              className="ml-2 inline-flex flex-shrink-0 items-center gap-1 rounded-md border border-blue-200/50 bg-blue-50 px-2 py-0.5 text-xs text-blue-600 transition-colors hover:border-blue-300/60 hover:bg-blue-100"
                              title="Add more files"
                            >
                              <Plus className="h-3 w-3" />
                              Add
                            </button>
                          )}
                        </div>
                      </div>
                      {onClearSelectedFiles && (
                        <button
                          onClick={onClearSelectedFiles}
                          className="ml-2 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                          title="Clear file selection"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                )}

                <InputBar
                  chat={chat}
                  isRecording={isRecording}
                  toggleRecording={toggleRecording}
                />

                <div className="mt-2 text-center text-xs text-gray-500">
                  Science GPT can make mistakes. Check important info.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Fixed Citation Sidebar - Positioned below header */}
      {isCitationSidebarOpen && (
        <div className="fixed top-14 right-0 z-30 h-[calc(100vh-3.5rem)] w-96 transform border-l border-gray-200 bg-white transition-transform duration-300 ease-in-out">
          <CitationSidebar
            isOpen={isCitationSidebarOpen}
            onClose={handleCloseCitationSidebar}
            sources={citationSources}
            messageId={citationMessageId}
          />
        </div>
      )}

      <Dialog open={isExitDialogOpen} onOpenChange={setIsExitDialogOpen}>
        <DialogContent className="rounded-xl">
          <DialogHeader>
            <DialogTitle>Leave this conversation?</DialogTitle>
            <DialogDescription>
              Your conversation history will not be saved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              className="rounded-lg border-gray-300 bg-white text-gray-700 hover:bg-gray-50 hover:text-gray-900"
              onClick={() => setIsExitDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              className="rounded-lg bg-gray-900 text-white hover:bg-gray-800"
              onClick={handleLeave}
            >
              Leave
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <style jsx global>{`
        /* Essential markdown styling */
        .markdown {
          font-size: 1rem;
          line-height: 1.6;
        }
        .markdown p {
          margin-bottom: 1rem;
        }
        .markdown p:last-child {
          margin-bottom: 0;
        }
        .markdown h1,
        .markdown h2,
        .markdown h3 {
          font-weight: 600;
          margin: 1.5rem 0 0.75rem 0;
        }
        .markdown h1 {
          font-size: 1.75rem;
        }
        .markdown h2 {
          font-size: 1.5rem;
        }
        .markdown h3 {
          font-size: 1.25rem;
        }
        .markdown ul,
        .markdown ol {
          padding-left: 1.75rem;
          margin-bottom: 1rem;
        }
        .markdown ul {
          list-style-type: disc;
        }
        .markdown ol {
          list-style-type: decimal;
        }
        .markdown li {
          margin-bottom: 0.5rem;
        }
        .markdown code {
          font-family: monospace;
          background-color: rgba(0, 0, 0, 0.1);
          padding: 0.1rem 0.2rem;
          border-radius: 3px;
          font-size: 0.9rem;
        }
        .markdown pre {
          background-color: rgba(0, 0, 0, 0.1);
          padding: 1rem;
          border-radius: 8px;
          overflow-x: auto;
          margin-bottom: 1rem;
        }
        .markdown pre code {
          background-color: transparent;
          padding: 0;
        }
        /* Dark theme adjustments */
        .bg-gray-700 .markdown {
          color: white;
        }
        .bg-gray-700 .markdown code {
          background-color: rgba(255, 255, 255, 0.2);
        }
        .bg-gray-700 .markdown pre {
          background-color: rgba(255, 255, 255, 0.1);
        }
        /* Auto-resize textarea */
        textarea {
          overflow-y: hidden;
        }
      `}</style>
    </>
  )
}
