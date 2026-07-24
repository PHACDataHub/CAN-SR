'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import GCHeader, { SRHeader } from '@/components/can-sr/headers'
import { authenticatedFetch, getAuthToken, getTokenType } from '@/lib/auth'
import { SAMPLE_YAML } from '@/components/can-sr/setup/sample-yaml'
import ManageUsersPopup from '@/components/can-sr/setup/manage-users-popup'
import CriteriaEditor from '@/components/can-sr/setup/criteria-editor'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Settings } from 'lucide-react'
import { useDictionary } from '../../DictionaryProvider'

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const tokenType = getTokenType()
  return token ? { Authorization: `${tokenType} ${token}` } : ({} as Record<string, string>)
}

 // CSV preview removed - client-side preview disabled

export default function CanSrSetupPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const srId = searchParams?.get('sr_id')
  const dict = useDictionary()

  const [manageOpen, setManageOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<any>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [yamlText, setYamlText] = useState<string>('')
  const [yamlLoading, setYamlLoading] = useState(false)
  const [yamlSaving, setYamlSaving] = useState(false)
  const [yamlSaveMessage, setYamlSaveMessage] = useState<string | null>(null)
  const [confirmOverwriteOpen, setConfirmOverwriteOpen] = useState(false)
  const [overwriteConfirmMessage, setOverwriteConfirmMessage] = useState(
    'This SR already has screening data. Updating criteria may invalidate existing screening results.',
  )

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const yamlInputRef = useRef<HTMLInputElement | null>(null)
  const yamlSaveMessageTimeoutRef = useRef<number | null>(null)

  // auth headers and SR state for Manage Users popup (mirrors sr/page.tsx)
  const token = getAuthToken()
  const tokenType = getTokenType()
  const authHeaders: Record<string, string> | undefined = token ? { Authorization: `${tokenType} ${token}` } : undefined

  const [sr, setSr] = useState<any>(null)
  const [, setSrLoading] = useState<boolean>(true)
  const [, setSrError] = useState<string | null>(null)

  const loadSr = useCallback(async () => {
    if (!srId) return null

    setSrLoading(true)
    setSrError(null)
    try {
      const res = await authenticatedFetch(
        `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}`,
      )
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        throw new Error(errBody?.detail || errBody?.error || `Failed to fetch SR (${res.status})`)
      }

      const data = await res.json().catch(() => ({}))
      setSr(data)
      return data
    } catch (err: any) {
      console.error('Error fetching SR:', err)
      setSrError(err?.message || 'Unable to load review')
      return null
    } finally {
      setSrLoading(false)
    }
  }, [srId])

  useEffect(() => {
    if (!srId) return
    void loadSr()
  }, [loadSr, srId])

  const clearYamlSaveMessageTimeout = useCallback(() => {
    if (yamlSaveMessageTimeoutRef.current !== null) {
      window.clearTimeout(yamlSaveMessageTimeoutRef.current)
      yamlSaveMessageTimeoutRef.current = null
    }
  }, [])

  const showYamlSaveMessage = useCallback(
    (message: string | null, autoClear = false) => {
      clearYamlSaveMessageTimeout()
      setYamlSaveMessage(message)

      if (message && autoClear) {
        yamlSaveMessageTimeoutRef.current = window.setTimeout(() => {
          setYamlSaveMessage(null)
          yamlSaveMessageTimeoutRef.current = null
        }, 3500)
      }
    },
    [clearYamlSaveMessageTimeout],
  )

  useEffect(() => {
    return () => {
      clearYamlSaveMessageTimeout()
    }
  }, [clearYamlSaveMessageTimeout])

  const normalizeYaml = useCallback((value: string | null | undefined) => {
    return (value || '').replace(/\r\n/g, '\n').trim()
  }, [])

  const getLastSavedYaml = useCallback(async () => {
    if (!srId) return SAMPLE_YAML

    const res = await authenticatedFetch(
      `/api/can-sr/reviews/create?sr_id=${encodeURIComponent(srId)}`,
    )
    const data = await res.json().catch(() => ({}))
    const criteria_yaml = data.criteria_yaml

    if (!criteria_yaml) {
      return SAMPLE_YAML
    }

    return criteria_yaml
  }, [srId])

  useEffect(() => {
    if (!srId) {
      router.replace('/can-sr')
      return
    }
    // try load project example YAML file (bundled in app)
    const loadLastSavedYaml = async () => {
      setYamlLoading(true)
      try {
        const criteria_yaml = await getLastSavedYaml()
        setYamlText(criteria_yaml || '')
      } finally {
        setYamlLoading(false)
      }
    }

    loadLastSavedYaml()
  }, [getLastSavedYaml, router, srId])

  // read selected file
  const handleFileSelected = async (f: File | null) => {
    setUploadResult(null)
    setUploadError(null)
    setFile(f)
  }

  // read uploaded YAML file and populate editor
  const handleYamlSelected = async (f: File | null) => {
    if (!f) return
    setYamlLoading(true)
    showYamlSaveMessage(null)
    try {
      const text = await f.text()
      setYamlText(text)
      // reset the file input so selecting the same file again will trigger change
      if (yamlInputRef.current) {
        try {
          ;(yamlInputRef.current as HTMLInputElement).value = ''
        } catch {
          // ignore
        }
      }
    } catch {
      showYamlSaveMessage('Failed to read YAML file')
    } finally {
      setYamlLoading(false)
    }
  }

  const onChooseFile = () => {
    fileInputRef.current?.click()
  }

  const handleUpload = async () => {
    setUploadResult(null)
    setUploadError(null)
    if (!srId) {
      setUploadError('Missing review id')
      return
    }
    if (!file) {
      setUploadError('No file selected')
      return
    }

    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)

      const headers = getAuthHeaders()
      // Do NOT set Content-Type; browser will set multipart boundary
      const res = await fetch(`/api/can-sr/citations/upload?sr_id=${encodeURIComponent(srId)}`, {
        method: 'POST',
        headers: headers,
        body: fd as any,
      })

      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const errMsg = data?.error || data?.detail || `Upload failed (${res.status})`
        setUploadError(errMsg)
      } else {
        setUploadResult(data)
        void loadSr()
      }
    } catch (err: any) {
      console.error('Upload error', err)
      setUploadError(err?.message || 'Network error during upload')
    } finally {
      setUploading(false)
    }
  }

  const hasExistingScreeningData = Boolean((sr?.screening_db || {}).table_name)

  const persistYaml = useCallback(async (forceUpdate = false) => {
    if (!srId) {
      showYamlSaveMessage('Missing review id')
      return false
    }

    setYamlSaving(true)
    showYamlSaveMessage(null)
    const submittedYaml = yamlText || ''
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    const timeoutId = window.setTimeout(() => {
      controller?.abort()
    }, 15000)

    try {
      const body = new URLSearchParams()
      body.set('criteria_yaml', submittedYaml)
      if (forceUpdate) {
        body.set('force', 'true')
      }

      const headers = getAuthHeaders()
      const res = await fetch(`/api/can-sr/reviews/edit?sr_id=${encodeURIComponent(srId)}`, {
        method: 'PUT',
        headers: {
          ...headers,
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        },
        body: body.toString(),
        signal: controller?.signal,
      })
      if (res.status === 409 && !forceUpdate) {
        const data = await res.json().catch(() => ({}))
        setOverwriteConfirmMessage(
          data?.detail ||
            'This SR already has screening data. Updating criteria may invalidate existing screening results.',
        )
        setConfirmOverwriteOpen(true)
        return false
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        showYamlSaveMessage(
          (data && (data.error || data.detail)) || `Save failed (${res.status})`,
        )
        return false
      }

      void loadSr()
      showYamlSaveMessage('Saved successfully', true)
      return true
    } catch (err: any) {
      const refreshedSr = await loadSr().catch(() => null)
      if (normalizeYaml(refreshedSr?.criteria_yaml) === normalizeYaml(submittedYaml)) {
        showYamlSaveMessage('Saved successfully', true)
        return true
      }

      if (err?.name === 'AbortError') {
        showYamlSaveMessage('Save timed out while waiting for the response. Please try again.')
        return false
      }

      showYamlSaveMessage(err?.message || 'Network error while saving')
      return false
    } finally {
      window.clearTimeout(timeoutId)
      setYamlSaving(false)
    }
  }, [loadSr, normalizeYaml, showYamlSaveMessage, srId, yamlText])

  const saveYaml = useCallback(() => {
    if (yamlSaving) {
      return
    }

    if (!hasExistingScreeningData) {
      void persistYaml(false)
      return
    }

    setOverwriteConfirmMessage(
      'This SR already has screening data. Updating criteria may invalidate existing screening results. Do you want to overwrite the existing configuration?',
    )
    setConfirmOverwriteOpen(true)
  }, [hasExistingScreeningData, persistYaml, yamlSaving])

  const confirmOverwriteAndSave = useCallback(async () => {
    setConfirmOverwriteOpen(false)
    await persistYaml(true)
  }, [persistYaml])

  const reloadLastSave = async () => {
    setYamlLoading(true)
    try {
      const criteria_yaml = await getLastSavedYaml()
      setYamlText(criteria_yaml)
    } finally {
      setYamlLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <GCHeader />

      <SRHeader
        title={dict.setup.title}
        backHref={`/can-sr/sr?sr_id=${encodeURIComponent(srId || '')}`}
        right={
          <div className="flex items-center">
            <button
              type="button"
              onClick={() => setManageOpen(true)}
              className="hidden items-center space-x-2 rounded-md border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 md:flex"
            >
              <Settings className="h-4 w-4 text-gray-600" />
              <span>{dict.cansr.manageUsers}</span>
            </button>
          </div>
        }
      />

      <main className="mx-auto max-w-4xl px-6 py-10">
        <h3 className="text-xl font-semibold text-gray-900">{dict.setup.pageTitle}</h3>
        <p className="mt-2 text-sm text-gray-600">
          {dict.setup.pageDesc}
        </p>

        <div className="mt-6 space-y-6">
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <label className="block text-sm font-medium text-gray-700">{dict.setup.uploadCitations}</label>
            <div className="mt-3 flex items-center gap-3">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.ris,.txt,text/csv,text/plain,application/x-research-info-systems"
                onChange={(e) => handleFileSelected(e.target.files ? e.target.files[0] : null)}
                className="hidden"
              />
              <button
                onClick={onChooseFile}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
              >
                {dict.setup.chooseFile}
              </button>

              <div className="ml-auto flex items-center space-x-2">
                <button
                  onClick={handleUpload}
                  disabled={!file || uploading}
                  className={`rounded-md px-3 py-2 text-sm font-medium text-white ${
                    !file || uploading ? 'bg-emerald-300' : 'bg-emerald-600 hover:bg-emerald-700'
                  }`}
                >
                  {uploading ? dict.setup.uploading : dict.setup.uploadCitationsButton}
                </button>
              </div>
            </div>

            {file ? (
              <div className="mt-3 text-sm text-gray-600">{dict.setup.selectedFile} {file.name}</div>
            ) : (
              <div className="mt-3 text-sm text-gray-500">{dict.setup.noFileSelected}</div>
            )}

            {uploadError ? <div className="mt-3 text-sm text-red-600">{uploadError}</div> : null}
            {uploadResult ? (
              <div className="mt-3 rounded-md bg-green-50 p-3 text-sm text-green-800">
                {uploadResult.message || 'Upload succeeded'}
              </div>
            ) : null}

          </div>

          <CriteriaEditor
            srId={srId || ''}
            hasScreeningData={hasExistingScreeningData}
            labels={dict.setup.criteriaBuilder as unknown as Record<string, string>}
          />

          {/* YAML editor */}
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium text-gray-700">{dict.setup.criteriaConfig}</label>
                <p className="mt-1 text-xs text-gray-500">{dict.setup.criteriaConfigDesc}</p>
              </div>

              <div className="flex items-center space-x-2">
                <input
                  ref={yamlInputRef}
                  type="file"
                  accept=".yaml,.yml,text/yaml"
                  onChange={(e) => handleYamlSelected(e.target.files ? e.target.files[0] : null)}
                  className="hidden"
                />

                <button
                  onClick={reloadLastSave}
                  className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  {dict.setup.reloadLastSave}
                </button>

                <button
                  onClick={() => yamlInputRef.current?.click()}
                  className="rounded-md border border-emerald-500 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100"
                >
                  {dict.setup.uploadYAML}
                </button>
              </div>
            </div>

              <div className="mt-3">
              <textarea
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                className="w-full min-h-[220px] resize-y rounded-md border border-gray-200 bg-white px-3 py-2 font-mono text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-emerald-200"
                placeholder="# criteria yaml"
              />
              {yamlLoading ? (
                <div className="mt-2 text-sm text-gray-500">Loading example...</div>
              ) : yamlSaveMessage ? (
                <div className="mt-2 text-sm text-gray-600">{yamlSaveMessage}</div>
              ) : null}

              <div className="mt-3 flex items-center space-x-2">
                <button
                  onClick={() => {
                    try {
                      const blob = new Blob([yamlText || ''], { type: 'text/yaml;charset=utf-8' })
                      const url = URL.createObjectURL(blob)
                      const a = document.createElement('a')
                      a.href = url
                      a.download = 'criteria.yaml'
                      document.body.appendChild(a)
                      a.click()
                      a.remove()
                      URL.revokeObjectURL(url)
                    } catch (err) {
                      console.error('Download failed', err)
                      setYamlSaveMessage('Download failed')
                      setTimeout(() => setYamlSaveMessage(null), 3000)
                    }
                  }}
                  className="rounded-md border border-emerald-500 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100"
                >
                  {dict.setup.downloadYAML}
                </button>

                <button
                  onClick={() => void saveYaml()}
                  disabled={yamlSaving}
                  className={`rounded-md px-3 py-2 text-sm font-medium text-white ${yamlSaving ? 'bg-emerald-300' : 'bg-emerald-600 hover:bg-emerald-700'}`}
                >
                  {yamlSaving ? dict.setup.saving : dict.setup.saveCriteria}
                </button>
              </div>
            </div>
          </div>

          {/* <div className="flex items-center justify-between">
            <div className="space-x-2">
              <button
                onClick={() => router.push(`/can-sr/l1-screen?sr_id=${encodeURIComponent(srId || '')}`)}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
              >
                Continue to Title & Abstract Screening
              </button>
            </div>
          </div> */}

        </div>
      </main>
      <AlertDialog open={confirmOverwriteOpen} onOpenChange={setConfirmOverwriteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Overwrite existing screening configuration?</AlertDialogTitle>
            <AlertDialogDescription>
              {overwriteConfirmMessage}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                showYamlSaveMessage('Update canceled', true)
              }}
            >
              Cancel
            </AlertDialogCancel>
            <button
              type="button"
              onClick={() => {
                void confirmOverwriteAndSave()
              }}
              disabled={yamlSaving}
              className={`rounded-md px-3 py-2 text-sm font-medium text-white ${yamlSaving ? 'bg-emerald-300' : 'bg-emerald-600 hover:bg-emerald-700'}`}
            >
              {yamlSaving ? dict.setup.saving : 'Overwrite and save'}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <ManageUsersPopup
          open={manageOpen}
          onClose={() => setManageOpen(false)}
          srId={srId}
          initialEmails={(sr && (sr.users || sr.user_emails || sr.allowed_users)) || []}
          authHeaders={authHeaders}
        />
    </div>
  )
}
