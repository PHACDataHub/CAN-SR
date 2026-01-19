'use client'

import React, { useState, useEffect } from 'react'
import { useUploadQueue } from './upload-queue-context'
import {
  FileText,
  X,
  ChevronUp,
  ChevronDown,
  CheckCircle,
  AlertCircle,
  Loader2,
  Upload,
  Clock,
} from 'lucide-react'
import { Button } from '@/components/ui/button'

export const UploadQueueNotification: React.FC = () => {
  const {
    queuedFiles,
    removeFromQueue,
    totalFiles,
    completedFiles,
    processingFiles,
    startProcessing,
    isProcessing,
  } = useUploadQueue()

  const [isExpanded, setIsExpanded] = useState(false)
  const [isVisible, setIsVisible] = useState(true)

  // Calculate derived values first
  const pendingFiles = queuedFiles.filter((f) => f.status === 'pending').length
  const errorFiles = queuedFiles.filter((f) => f.status === 'error').length

  // Helper function to format elapsed time
  const formatElapsedTime = (startTime: number) => {
    const elapsed = Math.floor((Date.now() - startTime) / 1000)
    if (elapsed < 60) return `${elapsed}s`
    const minutes = Math.floor(elapsed / 60)
    const seconds = elapsed % 60
    return `${minutes}m ${seconds}s`
  }

  // Auto-hide after all files are completed (including errors)
  useEffect(() => {
    if (totalFiles > 0 && completedFiles + errorFiles === totalFiles) {
      const timer = setTimeout(() => {
        setIsVisible(false)
      }, 3000) // Hide after 3 seconds when all files are done processing

      return () => clearTimeout(timer)
    }
  }, [totalFiles, completedFiles, errorFiles])

  // Show notification when new files are added
  useEffect(() => {
    if (totalFiles > 0) {
      setIsVisible(true)
    }
  }, [totalFiles])

  // Update timer every second for processing files
  const [, forceUpdate] = useState({})

  useEffect(() => {
    const hasProcessingFiles = queuedFiles.some(
      (f) =>
        (f.status === 'processing' || f.status === 'uploading') &&
        (f.processingStartTime || f.uploadStartTime),
    )

    if (!hasProcessingFiles) return

    const timer = setInterval(() => {
      // Force re-render to update elapsed time
      forceUpdate({})
    }, 1000)

    return () => clearInterval(timer)
  }, [queuedFiles])

  // Don't show if no files in queue or user dismissed it
  if (totalFiles === 0 || !isVisible) {
    return null
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'pending':
        return <Clock className="h-4 w-4 text-gray-400" />
      case 'uploading':
        return <Upload className="h-4 w-4 text-blue-500" />
      case 'processing':
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'error':
        return <AlertCircle className="h-4 w-4 text-red-500" />
      default:
        return <FileText className="h-4 w-4 text-gray-400" />
    }
  }

  const getStatusText = (status: string) => {
    switch (status) {
      case 'pending':
        return 'Waiting'
      case 'uploading':
        return 'Uploading'
      case 'processing':
        return 'Processing'
      case 'completed':
        return 'Completed'
      case 'error':
        return 'Failed'
      default:
        return status
    }
  }

  return (
    <div className="fixed right-4 bottom-4 z-50 w-80 max-w-[calc(100vw-2rem)]">
      <div className="rounded-lg border border-gray-200 bg-white shadow-lg">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 p-3">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-gray-600" />
            <span className="text-sm font-medium text-gray-900">
              Upload Queue ({completedFiles}/{totalFiles})
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="rounded p-1 hover:bg-gray-100"
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-gray-500" />
              ) : (
                <ChevronUp className="h-4 w-4 text-gray-500" />
              )}
            </button>
            <button
              onClick={() => setIsVisible(false)}
              className="rounded p-1 hover:bg-gray-100"
            >
              <X className="h-4 w-4 text-gray-500" />
            </button>
          </div>
        </div>

        {/* Status Summary */}
        <div className="p-3">
          {/* Status Summary */}
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-4">
              {processingFiles > 0 && (
                <span className="flex items-center gap-1 text-blue-600">
                  {processingFiles} processing
                </span>
              )}
              {pendingFiles > 0 && (
                <span className="flex items-center gap-1 text-gray-600">
                  <Clock className="h-3 w-3" />
                  {pendingFiles} waiting
                </span>
              )}
              {errorFiles > 0 && (
                <span className="flex items-center gap-1 text-red-600">
                  <AlertCircle className="h-3 w-3" />
                  {errorFiles} failed
                </span>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="mt-3 flex gap-2">
            {pendingFiles > 0 && !isProcessing && (
              <Button
                onClick={startProcessing}
                size="sm"
                className="flex-1 text-xs"
              >
                <Upload className="mr-1 h-3 w-3" />
                Start Processing
              </Button>
            )}
          </div>
        </div>

        {/* Expanded File List */}
        {isExpanded && (
          <div className="max-h-60 overflow-y-auto border-t border-gray-200">
            {queuedFiles.map((file) => (
              <div
                key={file.id}
                className="border-b border-gray-100 p-3 last:border-b-0"
              >
                <div className="flex items-center justify-between">
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    {getStatusIcon(file.status)}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-gray-900">
                        {file.filename}
                      </p>
                      <div className="flex items-center justify-between text-xs text-gray-500">
                        <span>{getStatusText(file.status)}</span>
                        <div className="flex items-center gap-2">
                          {file.status === 'completed' &&
                            file.chunksCreated && (
                              <span>({file.chunksCreated} chunks)</span>
                            )}
                          {(file.status === 'processing' ||
                            file.status === 'uploading') && (
                            <span className="font-mono text-xs text-blue-600">
                              {(() => {
                                const startTime =
                                  file.processingStartTime ||
                                  file.uploadStartTime
                                return startTime
                                  ? formatElapsedTime(startTime)
                                  : 'Starting...'
                              })()}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                  {(file.status === 'error' || file.status === 'completed') && (
                    <button
                      onClick={() => removeFromQueue(file.id)}
                      className="ml-2 rounded p-1 hover:bg-gray-100"
                    >
                      <X className="h-3 w-3 text-gray-400" />
                    </button>
                  )}
                </div>

                {/* Error Message */}
                {file.status === 'error' && file.error && (
                  <p className="mt-1 text-xs text-red-600">{file.error}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
