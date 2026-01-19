'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { FileText } from 'lucide-react'
import type { Citation } from './types'

interface CitationProps {
  citation: Citation
  children: React.ReactNode
}

export function CitationComponent({ citation, children }: CitationProps) {
  const [isOpen, setIsOpen] = useState(false)

  const formatScore = (score?: number) => {
    if (score === undefined) return 'N/A'
    return (score * 100).toFixed(1) + '%'
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="mx-0.5 h-auto rounded-sm border border-blue-200 p-0 px-1 py-0.5 text-sm font-medium text-blue-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
        >
          {children}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Source Citation
          </DialogTitle>
          <DialogDescription>
            Reference information for this citation
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Citation Info */}
          <div className="grid grid-cols-2 gap-4 rounded-lg bg-gray-50 p-4">
            <div>
              <label className="text-sm font-medium text-gray-600">
                Document
              </label>
              <p className="font-mono text-sm break-all">{citation.filename}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-600">
                Relevance Score
              </label>
              <Badge variant="secondary" className="mt-1">
                {formatScore(citation.distance)}
              </Badge>
            </div>
            {(citation.source_type || citation.metadata?.document_type) && (
              <div>
                <label className="text-sm font-medium text-gray-600">
                  Source Type
                </label>
                <p className="text-sm">
                  {citation.source_type === 'base' ||
                  citation.metadata?.document_type === 'base'
                    ? 'Base Knowledge'
                    : 'User Document'}
                </p>
              </div>
            )}
            {citation.chunk_index !== undefined && (
              <div>
                <label className="text-sm font-medium text-gray-600">
                  Chunk Index
                </label>
                <p className="text-sm">{citation.chunk_index}</p>
              </div>
            )}
            <div>
              <label className="text-sm font-medium text-gray-600">
                Citation ID
              </label>
              <p className="text-sm">[{citation.id}]</p>
            </div>
          </div>

          {/* Content Preview */}
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-600">
              Content
            </label>
            <div className="max-h-60 overflow-y-auto rounded-lg border bg-white p-4">
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {citation.content}
              </p>
            </div>
          </div>

          {/* Metadata */}
          {citation.metadata && Object.keys(citation.metadata).length > 0 && (
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-600">
                Metadata
              </label>
              <div className="rounded-lg bg-gray-50 p-3">
                <pre className="overflow-x-auto text-xs text-gray-700">
                  {JSON.stringify(citation.metadata, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 border-t pt-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(citation.content)
              }}
            >
              Copy Content
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsOpen(false)}
            >
              Close
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// Helper function to parse citations from text
export function parseCitations(text: string): {
  text: string
  citations: number[]
} {
  const citationRegex = /\[(\d+(?:,\s*\d+)*)\]/g
  const citations: number[] = []

  let match
  while ((match = citationRegex.exec(text)) !== null) {
    const citationNumbers = match[1].split(',').map((n) => parseInt(n.trim()))
    citations.push(...citationNumbers)
  }

  return {
    text,
    citations: [...new Set(citations)].sort((a, b) => a - b),
  }
}

// Component to render text with clickable citations
interface TextWithCitationsProps {
  text: string
  citations: Citation[]
}

export function TextWithCitations({ text, citations }: TextWithCitationsProps) {
  const citationMap = new Map(citations.map((c) => [c.id, c]))

  // Replace citation patterns with clickable components
  const parts = text.split(/(\[\d+(?:,\s*\d+)*\])/g)

  return (
    <>
      {parts.map((part, index) => {
        const citationMatch = part.match(/\[(\d+(?:,\s*\d+)*)\]/)

        if (citationMatch) {
          const citationNumbers = citationMatch[1]
            .split(',')
            .map((n) => parseInt(n.trim()))
          const validCitations = citationNumbers.filter((num) =>
            citationMap.has(num),
          )

          if (validCitations.length === 1) {
            const citation = citationMap.get(validCitations[0])
            if (citation) {
              return (
                <CitationComponent key={index} citation={citation}>
                  {part}
                </CitationComponent>
              )
            }
          } else if (validCitations.length > 1) {
            // For multiple citations, show the first one
            const citation = citationMap.get(validCitations[0])
            if (citation) {
              return (
                <CitationComponent key={index} citation={citation}>
                  {part}
                </CitationComponent>
              )
            }
          }
        }

        return <span key={index}>{part}</span>
      })}
    </>
  )
}
