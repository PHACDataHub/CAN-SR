'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { usePathname } from 'next/navigation'
import { getAuthToken, getTokenType } from '@/lib/auth'
import { Progress } from '@/components/ui/progress'
import { Pause, Play, X } from 'lucide-react'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

type RunAllJob = {
  job_id: string
  sr_id: string
  sr_name?: string
  step: 'l1' | 'l2' | 'extract' | string
  status: string
  total: number
  done: number
  skipped: number
  failed: number
}

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const tokenType = getTokenType()
  return token ? { Authorization: `${tokenType} ${token}` } : {}
}

export default function RunAllFloatingPanel() {
  const pathname = usePathname()
  const dict = useDictionary()

  const intervalRef = React.useRef<number | null>(null)

  // Hide on auth pages
  const hide = useMemo(() => {
    const p = String(pathname || '')
    return (
      p.includes('/login') ||
      p.includes('/register') ||
      p.includes('/sso-login')
    )
  }, [pathname])

  const [jobs, setJobs] = useState<RunAllJob[]>([])
  const [actingJobId, setActingJobId] = useState<string | null>(null)

  const fetchJobs = useCallback(async () => {
    try {
      const headers = getAuthHeaders()
      // If not authenticated, don't show anything
      if (!headers.Authorization) {
        setJobs([])
        if (intervalRef.current) {
          window.clearInterval(intervalRef.current)
          intervalRef.current = null
        }
        return
      }

      const res = await fetch('/api/can-sr/jobs/run-all/active', {
        method: 'GET',
        headers,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setJobs([])
        return
      }

      const nextJobs: RunAllJob[] = Array.isArray(data?.jobs) ? data.jobs : []
      setJobs(nextJobs)

      // Polling policy:
      // - If there are no active jobs, stop polling after this empty result.
      // - If all jobs are paused, stop polling; refresh will occur when the user
      //   performs an action (resume/cancel/start run-all).
      const allPaused =
        nextJobs.length > 0 &&
        nextJobs.every((j) => String(j.status || '').toLowerCase() === 'paused')
      if (nextJobs.length === 0 || allPaused) {
        if (intervalRef.current) {
          window.clearInterval(intervalRef.current)
          intervalRef.current = null
        }
      }
    } catch {
      setJobs([])
    }
  }, [])

  const ensurePolling = useCallback(() => {
    if (hide) return
    if (intervalRef.current) return
    // fetch immediately so UI updates without waiting for the first interval tick
    void fetchJobs()
    intervalRef.current = window.setInterval(() => {
      void fetchJobs()
    }, 5000)
  }, [fetchJobs, hide])

  useEffect(() => {
    if (hide) return
    ensurePolling()
    return () => {
      if (intervalRef.current) {
        window.clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [ensurePolling, hide])

  // When run-all state changes elsewhere in the app (start/resume/cancel),
  // refresh once and restart polling if needed.
  useEffect(() => {
    if (hide) return
    const handler = () => {
      ensurePolling()
      void fetchJobs()
    }
    window.addEventListener('run-all:changed', handler)
    return () => window.removeEventListener('run-all:changed', handler)
  }, [ensurePolling, fetchJobs, hide])

  const togglePause = async (job: RunAllJob) => {
    try {
      setActingJobId(job.job_id)
      // if everything is paused and we aren't polling, resuming should restart polling
      ensurePolling()
      const headers = getAuthHeaders()
      const st = String(job.status || '').toLowerCase()
      const next = st === 'paused' ? 'resume' : 'pause'
      await fetch(`/api/can-sr/jobs/run-all/${next}?job_id=${encodeURIComponent(job.job_id)}`,
        {
          method: 'POST',
          headers,
        },
      )

      try {
        window.dispatchEvent(new Event('run-all:changed'))
      } catch {
        // ignore
      }
    } finally {
      setActingJobId(null)
    }
  }

  const cancel = async (job: RunAllJob) => {
    try {
      setActingJobId(job.job_id)
      ensurePolling()
      const headers = getAuthHeaders()
      await fetch(`/api/can-sr/jobs/run-all/cancel?job_id=${encodeURIComponent(job.job_id)}`,
        {
          method: 'POST',
          headers,
        },
      )

      try {
        window.dispatchEvent(new Event('run-all:changed'))
      } catch {
        // ignore
      }
    } finally {
      setActingJobId(null)
    }
  }

  if (hide) return null
  if (!jobs || jobs.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-[360px] max-w-[90vw] flex-col gap-2">
      {jobs.slice(0, 5).map((job) => {
        const done = Number(job.done || 0)
        const skipped = Number(job.skipped || 0)
        const failed = Number(job.failed || 0)
        const total = Number(job.total || 0)
        const processed = done + skipped + failed
        const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0
        const st = String(job.status || '').toLowerCase()
        const stepLabel =
          job.step === 'l1'
            ? dict?.screening?.titleAbstract || 'Title/Abstract'
            : job.step === 'l2'
              ? dict?.screening?.fullText || 'Full text'
              : dict?.screening?.parameterExtraction || 'Extraction'

        return (
          <div
            key={job.job_id}
            className="rounded-lg border border-gray-200 bg-white p-3 shadow"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-gray-900">
                  {job.sr_name || job.sr_id}
                </div>
                <div className="mt-0.5 text-xs text-gray-600">
                  {dict?.screening?.runAllAI || 'Run all AI'} · {stepLabel}
                  {st === 'paused' ? ` · ${dict?.screening?.paused || 'Paused'}` : ''}
                </div>
              </div>

              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={actingJobId === job.job_id}
                  onClick={() => togglePause(job)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
                  title={st === 'paused' ? (dict?.screening?.resume || 'Resume') : (dict?.screening?.pause || 'Pause')}
                >
                  {st === 'paused' ? (
                    <Play className="h-4 w-4" />
                  ) : (
                    <Pause className="h-4 w-4" />
                  )}
                </button>

                <button
                  type="button"
                  disabled={actingJobId === job.job_id}
                  onClick={() => cancel(job)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-gray-200 bg-white text-red-600 hover:bg-red-50 disabled:bg-gray-100 disabled:text-gray-400"
                  title={dict?.common?.cancel || 'Cancel'}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="mt-2">
              <div className="flex items-center justify-between text-xs text-gray-600">
                <span>
                  {total > 0
                    ? `${processed}/${total}`
                    : dict?.screening?.preparing || 'Preparing…'}
                </span>
                <span className="text-[11px] text-gray-500">
                  skipped: {skipped} · failed: {failed}
                </span>
              </div>
              <div className="mt-1">
                <Progress value={pct} />
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
