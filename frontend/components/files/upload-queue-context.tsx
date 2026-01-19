'use client'

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from 'react'
import { toast } from 'react-hot-toast'
import { getAuthToken } from '@/lib/auth'

export interface QueuedFile {
  id: string
  file: File
  filename: string
  fileSize: number
  status: 'pending' | 'uploading' | 'processing' | 'completed' | 'error'
  chunkingMethod: string
  documentId?: string
  chunksCreated?: number
  error?: string
  uploadStartTime?: number
  processingStartTime?: number
}

interface UploadQueueContextType {
  queuedFiles: QueuedFile[]
  addToQueue: (files: File[], chunkingMethod: string) => void
  removeFromQueue: (fileId: string) => void
  startProcessing: () => void
  isProcessing: boolean
  totalFiles: number
  completedFiles: number
  processingFiles: number
}

const UploadQueueContext = createContext<UploadQueueContextType | undefined>(
  undefined,
)

export const useUploadQueue = () => {
  const context = useContext(UploadQueueContext)
  if (!context) {
    throw new Error('useUploadQueue must be used within an UploadQueueProvider')
  }
  return context
}

export const UploadQueueProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([])
  const [isProcessing, setIsProcessing] = useState(false)

  // Calculate stats
  const totalFiles = queuedFiles.length
  const completedFiles = queuedFiles.filter(
    (f) => f.status === 'completed',
  ).length
  const processingFiles = queuedFiles.filter(
    (f) => f.status === 'uploading' || f.status === 'processing',
  ).length

  const addToQueue = useCallback((files: File[], chunkingMethod: string) => {
    const newFiles: QueuedFile[] = files.map((file) => ({
      id: `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`,
      file,
      filename: file.name,
      fileSize: file.size,
      status: 'pending',
      chunkingMethod,
    }))

    setQueuedFiles((prev) => {
      // Check for duplicates by filename to avoid duplicate entries
      const existingFilenames = prev.map((f) => f.filename)
      const uniqueNewFiles = newFiles.filter(
        (f) => !existingFilenames.includes(f.filename),
      )
      return [...prev, ...uniqueNewFiles]
    })

    // Show initial notification
    if (newFiles.length === 1) {
      toast.success(`Added ${newFiles[0].filename} to upload queue`, {
        duration: 3000,
        icon: '📄',
      })
    } else {
      toast.success(`Added ${newFiles.length} files to upload queue`, {
        duration: 3000,
        icon: '📄',
      })
    }
  }, [])

  const removeFromQueue = useCallback((fileId: string) => {
    setQueuedFiles((prev) => prev.filter((f) => f.id !== fileId))
  }, [])

  const uploadFile = useCallback(
    async (queuedFile: QueuedFile) => {
      try {
        // Update status to uploading
        setQueuedFiles((prev) =>
          prev.map((f) =>
            f.id === queuedFile.id
              ? { ...f, status: 'uploading', uploadStartTime: Date.now() }
              : f,
          ),
        )

        const token = getAuthToken()
        if (!token) {
          throw new Error('Authentication required')
        }

        const formData = new FormData()
        formData.append('file', queuedFile.file)
        formData.append('chunking_method', queuedFile.chunkingMethod)

        const response = await fetch('/api/files/upload', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        })

        if (!response.ok) {
          const errorData = await response.json()
          console.log('Upload error response:', {
            status: response.status,
            data: errorData,
          })

          // Handle duplicate file responses (409 Conflict)
          if (response.status === 409) {
            // The response structure is: { error: { error: 'duplicate_file', message: '...', duplicate_info: {...} } }
            const duplicateData =
              errorData.error || errorData.detail || errorData

            // Check for duplicate error formats
            if (
              duplicateData.error === 'duplicate_file' ||
              duplicateData.message?.includes('already exists') ||
              duplicateData.message?.includes('duplicate')
            ) {
              const message =
                duplicateData.message ||
                `File "${queuedFile.filename}" already exists in your library.`

              // Remove the file from queue since it's a duplicate
              setQueuedFiles((prev) =>
                prev.filter((f) => f.id !== queuedFile.id),
              )

              // Show warning toast
              toast.error(message, {
                duration: 5000,
                icon: '⚠️',
              })

              return // Don't throw error, just return
            }
          }

          // Handle other errors
          const errorMessage =
            typeof errorData.error === 'string'
              ? errorData.error
              : errorData.message ||
                (typeof errorData.detail === 'string'
                  ? errorData.detail
                  : errorData.detail?.message) ||
                'Upload failed'

          throw new Error(errorMessage)
        }

        const result = await response.json()

        // Update to processing status
        setQueuedFiles((prev) =>
          prev.map((f) =>
            f.id === queuedFile.id
              ? {
                  ...f,
                  status: 'processing',
                  documentId: result.document_id,
                  processingStartTime: Date.now(),
                }
              : f,
          ),
        )

        // Start checking processing status
        checkProcessingStatus(result.document_id, queuedFile.id)
      } catch (error) {
        console.error('Upload error:', error)
        const errorMessage =
          error instanceof Error ? error.message : 'Upload failed'

        setQueuedFiles((prev) =>
          prev.map((f) =>
            f.id === queuedFile.id
              ? {
                  ...f,
                  status: 'error',
                  error: errorMessage,
                }
              : f,
          ),
        )

        // Show appropriate toast message
        if (errorMessage.startsWith('DUPLICATE_FILE:')) {
          const cleanMessage = errorMessage.replace('DUPLICATE_FILE:', '')
          toast(`📄 File already exists: ${queuedFile.filename}`, {
            duration: 6000,
            icon: '📄',
            style: {
              background: '#fef3c7',
              color: '#92400e',
              border: '1px solid #fbbf24',
            },
          })
          // Update the error message to be more user-friendly
          setQueuedFiles((prev) =>
            prev.map((f) =>
              f.id === queuedFile.id
                ? {
                    ...f,
                    status: 'error',
                    error: `Duplicate file: ${cleanMessage}`,
                  }
                : f,
            ),
          )
        } else if (
          errorMessage.includes('already exists') ||
          errorMessage.includes('duplicate')
        ) {
          toast(`📄 File already exists: ${queuedFile.filename}`, {
            duration: 6000,
            icon: '📄',
            style: {
              background: '#fef3c7',
              color: '#92400e',
              border: '1px solid #fbbf24',
            },
          })
        } else {
          toast.error(`❌ Failed to upload ${queuedFile.filename}`, {
            duration: 5000,
            icon: '❌',
          })
        }
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [queuedFiles],
  )

  const checkProcessingStatus = useCallback(
    async (documentId: string, fileId: string) => {
      const maxAttempts = 60 // 10 minutes max
      let attempts = 0

      const checkStatus = async () => {
        try {
          const token = getAuthToken()
          if (!token) return

          const response = await fetch(
            `/api/files/list?search=${encodeURIComponent('')}`,
            {
              headers: { Authorization: `Bearer ${token}` },
            },
          )

          if (!response.ok) return

          const data = await response.json()
          const document = data.documents?.find(
            (doc: any) => doc.document_id === documentId,
          )

          if (document) {
            // Map backend status to queue status
            let queueStatus = 'processing'
            if (document.processing_status === 'completed') {
              queueStatus = 'completed'
            } else if (
              document.processing_status === 'failed' ||
              document.processing_status === 'error'
            ) {
              queueStatus = 'error'
            } else if (document.processing_status === 'uploaded') {
              queueStatus = 'processing' // Uploaded but not yet processed
            } else if (document.processing_status === 'uploading') {
              queueStatus = 'uploading'
            }

            // Update queue status to match backend
            setQueuedFiles((prev) =>
              prev.map((f) =>
                f.id === fileId
                  ? {
                      ...f,
                      status: queueStatus as any,
                      chunksCreated: document.chunk_count || undefined,
                      // Keep existing timing if not changing to completed
                      ...(queueStatus !== 'completed' && f.processingStartTime
                        ? { processingStartTime: f.processingStartTime }
                        : {}),
                    }
                  : f,
              ),
            )

            // Show completion notification only when completed
            if (document.processing_status === 'completed') {
              const queuedFile = queuedFiles.find((f) => f.id === fileId)
              if (queuedFile) {
                toast.success(
                  `${queuedFile.filename} processed successfully!`,
                  {
                    duration: 4000,
                    icon: '✅',
                  },
                )
              }
              return // Stop checking when completed
            }

            // Show error notification if failed
            if (
              document.processing_status === 'failed' ||
              document.processing_status === 'error'
            ) {
              const queuedFile = queuedFiles.find((f) => f.id === fileId)
              if (queuedFile) {
                toast.error(`${queuedFile.filename} processing failed`, {
                  duration: 5000,
                  icon: '❌',
                })
              }
              return // Stop checking when failed
            }
          }

          attempts++
          if (attempts < maxAttempts) {
            setTimeout(checkStatus, 10000) // Check every 10 seconds
          } else {
            // Timeout - mark as error
            setQueuedFiles((prev) =>
              prev.map((f) =>
                f.id === fileId
                  ? { ...f, status: 'error', error: 'Processing timeout' }
                  : f,
              ),
            )
          }
        } catch (error) {
          console.error('Status check error:', error)
          attempts++
          if (attempts < maxAttempts) {
            setTimeout(checkStatus, 10000)
          }
        }
      }

      setTimeout(checkStatus, 5000) // Start checking after 5 seconds
    },
    [],
  )

  const startProcessing = useCallback(async () => {
    const pendingFiles = queuedFiles.filter((f) => f.status === 'pending')
    if (pendingFiles.length === 0) return

    setIsProcessing(true)

    // Show processing start notification
    toast.success(
      `Processing ${pendingFiles.length} file${pendingFiles.length > 1 ? 's' : ''}...`,
      {
        duration: 4000,
        icon: '⚡',
      },
    )

    // Process files sequentially to avoid overwhelming the server
    for (const file of pendingFiles) {
      await uploadFile(file)
      // Small delay between uploads
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }

    setIsProcessing(false)
  }, [queuedFiles, uploadFile])

  // Check for completion and show notification, then auto-clear
  useEffect(() => {
    const allCompleted =
      queuedFiles.length > 0 &&
      queuedFiles.every((f) => f.status === 'completed' || f.status === 'error')
    const hasCompleted = queuedFiles.some((f) => f.status === 'completed')

    if (allCompleted && hasCompleted && !isProcessing) {
      const completedCount = queuedFiles.filter(
        (f) => f.status === 'completed',
      ).length
      const errorCount = queuedFiles.filter((f) => f.status === 'error').length

      if (errorCount === 0) {
        toast.success(
          `All ${completedCount} document${completedCount > 1 ? 's' : ''} processed successfully!`,
          {
            duration: 6000,
            icon: '🎉',
          },
        )
      } else {
        toast.success(
          `${completedCount} document${completedCount > 1 ? 's' : ''} processed successfully. ${errorCount} failed.`,
          {
            duration: 6000,
            icon: '⚠️',
          },
        )
      }

      // Auto-clear all files after 5 seconds
      setTimeout(() => {
        setQueuedFiles([])
      }, 5000)
    }
  }, [queuedFiles, isProcessing])

  return (
    <UploadQueueContext.Provider
      value={{
        queuedFiles,
        addToQueue,
        removeFromQueue,
        startProcessing,
        isProcessing,
        totalFiles,
        completedFiles,
        processingFiles,
      }}
    >
      {children}
    </UploadQueueContext.Provider>
  )
}
