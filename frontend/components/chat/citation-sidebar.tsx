'use client'

import { useState } from 'react'
import {
  X,
  ExternalLink,
  FileText,
  Globe,
  Database,
  Copy,
  Check,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { Citation } from './types'

interface CitationSidebarProps {
  isOpen: boolean
  onClose: () => void
  sources: Citation[]
}

export function CitationSidebar({
  isOpen,
  onClose,
  sources,
}: CitationSidebarProps) {
  const [modalSource, setModalSource] = useState<Citation | null>(null)
  const [copiedField, setCopiedField] = useState<string | null>(null)

  if (!isOpen) return null

  const getSourceIcon = (sourceType: string) => {
    switch (sourceType?.toLowerCase()) {
      case 'google':
      case 'web':
        return <Globe className="h-4 w-4 text-blue-500" />
      case 'pdf':
      case 'document':
        return <FileText className="h-4 w-4 text-red-500" />
      default:
        return <Database className="h-4 w-4 text-gray-500" />
    }
  }

  const isWebSource = (source: Citation) => {
    return (
      !!(source as any).url ||
      !!(source as any).snippet ||
      source.source_type === 'google'
    )
  }

  const getSourceTitle = (source: Citation, index: number) => {
    return (source as any).title || source.filename || `Source ${index + 1}`
  }

  const getSourceContent = (source: Citation) => {
    const snippet = (source as any).snippet || source.content || ''
    const title = (source as any).title || source.filename || ''

    if (snippet === title && title.includes('.')) {
      return `Information sourced from ${title}`
    }

    if (snippet.startsWith('Content from ') && snippet.includes('.')) {
      return `Information sourced from ${snippet.replace('Content from ', '')}`
    }

    return (
      snippet || `Information sourced from ${title}` || 'No content available'
    )
  }

  const truncateText = (text: string, maxLength: number = 200) => {
    return text.length > maxLength ? `${text.substring(0, maxLength)}...` : text
  }

  const handleCopy = async (text: string, fieldName: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedField(fieldName)
      setTimeout(() => setCopiedField(null), 2000)
    } catch (err) {
      console.error('Failed to copy text: ', err)
    }
  }

  const CodeBlock = ({
    title,
    content,
    fieldName,
  }: {
    title: string
    content: string
    fieldName: string
  }) => (
    <div className="group relative">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium tracking-wide text-gray-600 uppercase">
          {title}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => handleCopy(content, fieldName)}
          className="h-6 w-6 p-0 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-gray-200"
        >
          {copiedField === fieldName ? (
            <Check className="h-3 w-3 text-green-600" />
          ) : (
            <Copy className="h-3 w-3 text-gray-400" />
          )}
        </Button>
      </div>
      <div className="max-h-32 overflow-auto rounded-md border border-gray-200 bg-gray-50 p-3 font-mono text-sm text-gray-800">
        <pre className="break-words whitespace-pre-wrap">{content}</pre>
      </div>
    </div>
  )

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 p-4">
        <div className="flex items-center gap-2">
          <FileText className="h-5 w-5 text-gray-600" />
          <h2 className="text-lg font-semibold text-gray-900">Sources</h2>
          <span className="rounded-full bg-gray-200 px-2 py-0.5 text-sm text-gray-500">
            {sources.length}
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
          className="h-8 w-8 p-0 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Content-to-Source Mapping for Web Search */}
      {(() => {
        const groundingSupports =
          sources.length > 0 && sources[0].metadata?.grounding_supports

        if (groundingSupports && groundingSupports.length > 0) {
          return (
            <div className="flex-1 overflow-y-auto">
              <div className="border-b border-gray-200 bg-gray-50 p-4">
                <div className="mb-3 flex items-center gap-2">
                  <FileText className="h-4 w-4 text-gray-600" />
                  <span className="text-sm font-semibold text-gray-900">
                    Text Segments & Sources
                  </span>
                </div>
                <div className="space-y-3">
                  {groundingSupports.map((support: any, index: number) => (
                    <div
                      key={index}
                      className="rounded-lg border border-gray-200 bg-white p-3"
                    >
                      {/* Text segment */}
                      <div className="mb-2">
                        <p className="text-sm leading-relaxed text-gray-800 italic">
                          &ldquo;{support.text}&rdquo;
                        </p>
                      </div>

                      {/* Sources for this segment */}
                      <div className="flex flex-wrap gap-2">
                        {/* Remove duplicates and map to actual sources */}
                        {Array.from(new Set(support.source_indices || [])).map(
                          (sourceIndex, idx) => {
                            const source = sources[sourceIndex as number]
                            if (!source) return null

                            return (
                              <a
                                key={idx}
                                href={source.url || '#'}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-600 transition-colors hover:bg-blue-100 hover:text-blue-800"
                              >
                                <Globe className="h-3 w-3" />
                                {source.title || source.filename}
                              </a>
                            )
                          },
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )
        } else {
          // Local search - show traditional source list
          return (
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {sources.map((source, index) => (
                <div
                  key={source.id || index}
                  className="rounded-lg border border-gray-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md"
                >
                  <div className="p-4">
                    {/* Source Header */}
                    <div className="mb-4 flex items-start justify-between">
                      <div className="flex flex-1 items-start gap-3">
                        {/* Priority indicator */}
                        <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-500 text-xs font-semibold text-white">
                          {index + 1}
                        </div>
                        {getSourceIcon(source.source_type || '')}
                        <div className="min-w-0 flex-1">
                          <h3 className="text-sm leading-tight font-semibold text-gray-900">
                            {getSourceTitle(source, index)}
                          </h3>
                          <div className="mt-2 flex flex-wrap gap-1">
                            {source.source_type && (
                              <span className="inline-flex items-center rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-800">
                                {source.source_type}
                              </span>
                            )}
                            {source.distance !== undefined && (
                              <span className="inline-flex items-center rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-800">
                                {source.distance.toFixed(3)}
                              </span>
                            )}
                            {source.chunk_index !== undefined && (
                              <span className="inline-flex items-center rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-800">
                                #{source.chunk_index}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setModalSource(source)}
                        className="ml-2 h-8 w-8 flex-shrink-0 p-0 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-600"
                        title="Expand to full view"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </Button>
                    </div>

                    {/* Content Preview */}
                    {getSourceContent(source) && (
                      <div className="mb-3">
                        <CodeBlock
                          title="Content"
                          content={truncateText(getSourceContent(source), 150)}
                          fieldName={`content-${source.id || index}`}
                        />
                      </div>
                    )}

                    {/* Metadata Preview */}
                    {source.metadata &&
                      Object.keys(source.metadata).length > 0 && (
                        <div className="mb-3">
                          <CodeBlock
                            title="Metadata"
                            content={Object.entries(source.metadata)
                              .map(([key, value]) => `${key}: ${value}`)
                              .join('\n')}
                            fieldName={`metadata-${source.id || index}`}
                          />
                        </div>
                      )}
                  </div>
                </div>
              ))}
            </div>
          )
        }
      })()}

      {/* Footer */}
      <div className="flex-shrink-0 border-t border-gray-200 bg-gray-50 p-3">
        <p className="text-center text-xs text-gray-500">
          These sources were used to generate the response above
        </p>
      </div>

      {/* Expanded Source Modal */}
      <Dialog open={!!modalSource} onOpenChange={() => setModalSource(null)}>
        <DialogContent className="flex max-h-[80vh] max-w-4xl flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {getSourceIcon(modalSource?.source_type || '')}
              {modalSource ? getSourceTitle(modalSource, 0) : 'Source Details'}
            </DialogTitle>
            {/* Domain and Visit button for web sources */}
            {modalSource && isWebSource(modalSource) && (
              <div className="flex items-center gap-3 text-sm text-gray-600">
                <span>Source: {modalSource.title || modalSource.filename}</span>
                <a
                  href={(modalSource as any).url || '#'}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-3 py-1.5 font-medium text-blue-600 transition-colors hover:bg-blue-100 hover:text-blue-800"
                >
                  <ExternalLink className="h-4 w-4" />
                  Visit Source
                </a>
              </div>
            )}
          </DialogHeader>

          <div className="flex-1 space-y-4 overflow-auto">
            {/* Full Content or Snippet */}
            {modalSource && getSourceContent(modalSource) && (
              <CodeBlock
                title={
                  isWebSource(modalSource) ? 'Full Snippet' : 'Full Content'
                }
                content={getSourceContent(modalSource)}
                fieldName="modal-content"
              />
            )}

            {/* Full Metadata */}
            {modalSource?.metadata &&
              Object.keys(modalSource.metadata).length > 0 && (
                <CodeBlock
                  title="Complete Metadata"
                  content={JSON.stringify(modalSource.metadata, null, 2)}
                  fieldName="modal-metadata"
                />
              )}

            {/* Technical Details */}
            <div className="grid grid-cols-2 gap-4">
              {modalSource?.source_type && (
                <CodeBlock
                  title="Source Type"
                  content={modalSource.source_type}
                  fieldName="modal-source-type"
                />
              )}

              {modalSource?.document_id && (
                <CodeBlock
                  title="Document ID"
                  content={modalSource.document_id}
                  fieldName="modal-doc-id"
                />
              )}
              {modalSource?.distance !== undefined && (
                <CodeBlock
                  title="Relevance Score"
                  content={modalSource.distance.toFixed(6)}
                  fieldName="modal-relevance"
                />
              )}
              {modalSource?.chunk_index !== undefined && (
                <CodeBlock
                  title="Chunk Index"
                  content={modalSource.chunk_index.toString()}
                  fieldName="modal-chunk"
                />
              )}
              {modalSource?.chunk_method && (
                <CodeBlock
                  title="Chunk Method"
                  content={modalSource.chunk_method}
                  fieldName="modal-method"
                />
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
