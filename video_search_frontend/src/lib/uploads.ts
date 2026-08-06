import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE_URL } from './api'

export type UploadStatus = 'uploading' | 'processing' | 'indexed' | 'failed'

export interface UploadItem {
  id: string
  name: string
  size: number
  progress: number // 0..100
  status: UploadStatus
  error?: string
}

const ACCEPTED_EXTENSIONS = ['mp4', 'mov', 'avi']
const MAX_BYTES = 2 * 1024 ** 3 // 2GB placeholder limit
const POLL_INTERVAL_MS = 1000
const TERMINAL_JOB_STATUSES = new Set(['complete', 'completed_with_errors', 'partial', 'failed', 'cancelled'])
const FAILED_JOB_STATUSES = new Set(['failed', 'cancelled'])

function extensionOf(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

interface JobStatusPayload {
  status: string
  progress: number
  errors: { message: string }[]
}

// Real ingestion pipeline: upload the file to /api/processing/jobs, start it,
// then poll job status until it reaches a terminal state. index_qdrant=true
// is required for the upload to actually become searchable from the Home
// page — without it the backend still processes the video but never writes
// its vectors to Qdrant.
function uploadVideo(file: File, onProgress: (percent: number) => void, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/api/processing/jobs`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress((event.loaded / event.total) * 100)
    }
    xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'))
    xhr.onerror = () => reject(new Error('Upload failed. Is the backend running?'))
    xhr.onload = () => {
      let body: { job_id?: string; detail?: string } = {}
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        // non-JSON error body handled by the status check below
      }
      if (xhr.status !== 201 || !body.job_id) {
        reject(new Error(body.detail ?? `Upload failed (${xhr.status})`))
        return
      }
      resolve(body.job_id)
    }
    signal.addEventListener('abort', () => xhr.abort())

    const form = new FormData()
    form.append('video', file)
    form.append('configuration', JSON.stringify({ index_qdrant: true }))
    xhr.send(form)
  })
}

async function startJob(jobId: string, signal: AbortSignal): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/processing/jobs/${jobId}/start`, { method: 'POST', signal })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `Could not start processing (${res.status})`)
  }
}

async function pollJobUntilTerminal(
  jobId: string,
  onUpdate: (status: string, progressPercent: number) => void,
  signal: AbortSignal,
): Promise<JobStatusPayload> {
  while (true) {
    const res = await fetch(`${API_BASE_URL}/api/processing/jobs/${jobId}`, { signal })
    if (!res.ok) throw new Error(`Could not read job status (${res.status})`)
    const job = (await res.json()) as JobStatusPayload
    onUpdate(job.status, Math.round((job.progress ?? 0) * 100))
    if (TERMINAL_JOB_STATUSES.has(job.status)) return job
    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, POLL_INTERVAL_MS)
      signal.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(new DOMException('Polling aborted', 'AbortError'))
      })
    })
  }
}

export function useUploads() {
  const [items, setItems] = useState<UploadItem[]>([])
  const controllers = useRef<Map<string, AbortController>>(new Map())

  const update = useCallback((id: string, patch: Partial<UploadItem>) => {
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)))
  }, [])

  const runUpload = useCallback(
    async (id: string, file: File) => {
      const controller = new AbortController()
      controllers.current.set(id, controller)
      try {
        const jobId = await uploadVideo(
          file,
          (percent) => update(id, { progress: percent }),
          controller.signal,
        )
        update(id, { status: 'processing', progress: 0 })
        await startJob(jobId, controller.signal)
        const finalJob = await pollJobUntilTerminal(
          jobId,
          (_status, progressPercent) => update(id, { progress: progressPercent }),
          controller.signal,
        )
        if (FAILED_JOB_STATUSES.has(finalJob.status)) {
          const message = finalJob.errors[finalJob.errors.length - 1]?.message ?? `Processing ${finalJob.status}`
          update(id, { status: 'failed', error: message })
        } else {
          update(id, { status: 'indexed' })
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        update(id, { status: 'failed', error: err instanceof Error ? err.message : 'Upload failed' })
      } finally {
        controllers.current.delete(id)
      }
    },
    [update],
  )

  const addFiles = useCallback(
    (fileList: FileList | File[]) => {
      const files = Array.from(fileList)
      for (const file of files) {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        const ext = extensionOf(file.name)

        if (!ACCEPTED_EXTENSIONS.includes(ext)) {
          setItems((prev) => [
            ...prev,
            { id, name: file.name, size: file.size, progress: 0, status: 'failed', error: 'Unsupported format' },
          ])
          continue
        }
        if (file.size > MAX_BYTES) {
          setItems((prev) => [
            ...prev,
            { id, name: file.name, size: file.size, progress: 0, status: 'failed', error: 'Exceeds 2GB limit' },
          ])
          continue
        }

        setItems((prev) => [...prev, { id, name: file.name, size: file.size, progress: 0, status: 'uploading' }])
        void runUpload(id, file)
      }
    },
    [runUpload],
  )

  useEffect(() => {
    const inFlight = controllers.current
    return () => {
      inFlight.forEach((controller) => controller.abort())
    }
  }, [])

  return { items, addFiles }
}
