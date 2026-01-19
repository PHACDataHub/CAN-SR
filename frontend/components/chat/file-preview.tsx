'use client'

import { Button } from '@/components/ui/button'
import { FileText, X, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import type { UploadedFile } from './types'

interface FilePreviewProps {
  uploadedFiles: UploadedFile[]
  removeFile: (index: number) => void
}

export function FilePreview({ uploadedFiles, removeFile }: FilePreviewProps) {
  if (uploadedFiles.length === 0) return null

  return (
    <div className="mb-4 max-h-36 overflow-y-auto rounded-2xl border border-gray-200 bg-gray-50 p-3 shadow-sm">
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-xs font-medium text-gray-600">Uploaded files</p>
        <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-700">
          {uploadedFiles.length} {uploadedFiles.length === 1 ? 'file' : 'files'}
        </span>
      </div>
      <div className="space-y-2">
        {uploadedFiles.map((uploadedFile, index) => (
          <div
            key={index}
            className="flex items-center justify-between rounded-xl bg-white p-2 px-3 shadow-sm transition-all hover:bg-gray-50"
          >
            <div className="flex items-center gap-2 truncate">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-50">
                {getStatusIcon(uploadedFile.status)}
              </div>
              <div className="flex flex-col">
                <span className="truncate text-sm font-medium text-gray-700">
                  {uploadedFile.file.name}
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">
                    {formatFileSize(uploadedFile.file.size)}
                  </span>
                  {uploadedFile.status !== 'pending' && (
                    <span
                      className={`text-xs font-medium ${getStatusColor(uploadedFile.status)}`}
                    >
                      {getStatusText(uploadedFile.status)}
                    </span>
                  )}
                </div>
                {uploadedFile.status === 'uploading' &&
                  uploadedFile.progress && (
                    <div className="mt-1 h-1 w-full rounded-full bg-gray-200">
                      <div
                        className="h-1 rounded-full bg-blue-500 transition-all duration-300"
                        style={{ width: `${uploadedFile.progress}%` }}
                      />
                    </div>
                  )}
                {uploadedFile.error && (
                  <span className="mt-1 text-xs text-red-500">
                    {uploadedFile.error}
                  </span>
                )}
                {uploadedFile.status === 'completed' &&
                  uploadedFile.chunks_created && (
                    <span className="mt-1 text-xs text-green-600">
                      {uploadedFile.chunks_created} chunks created
                    </span>
                  )}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 rounded-full p-0 hover:bg-red-50 hover:text-red-500"
              onClick={() => removeFile(index)}
              disabled={
                uploadedFile.status === 'uploading' ||
                uploadedFile.status === 'processing'
              }
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}

function getStatusIcon(status: UploadedFile['status']) {
  switch (status) {
    case 'pending':
      return <FileText className="h-4 w-4 text-blue-500" />
    case 'uploading':
    case 'processing':
      return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
    case 'completed':
      return <CheckCircle className="h-4 w-4 text-green-500" />
    case 'error':
      return <AlertCircle className="h-4 w-4 text-red-500" />
    default:
      return <FileText className="h-4 w-4 text-blue-500" />
  }
}

function getStatusColor(status: UploadedFile['status']) {
  switch (status) {
    case 'uploading':
    case 'processing':
      return 'text-blue-600'
    case 'completed':
      return 'text-green-600'
    case 'error':
      return 'text-red-600'
    default:
      return 'text-gray-600'
  }
}

function getStatusText(status: UploadedFile['status']) {
  switch (status) {
    case 'uploading':
      return 'Uploading...'
    case 'processing':
      return 'Processing...'
    case 'completed':
      return 'Ready'
    case 'error':
      return 'Failed'
    default:
      return ''
  }
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'

  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}
