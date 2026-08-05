import { useCallback, useEffect, useRef, useState } from 'react'

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

function extensionOf(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

/**
 * There's no real upload/indexing endpoint wired up for this page yet, so
 * progress here is simulated client-side — enough to preview the drop
 * zone, per-file progress bar, and status states end-to-end. Swap this
 * hook's internals for real XHR/fetch upload progress + a job-status poll
 * once an ingestion endpoint exists.
 */
export function useUploads() {
  const [items, setItems] = useState<UploadItem[]>([])
  const uploadTimers = useRef<Map<string, number>>(new Map())
  const settleTimers = useRef<Map<string, number>>(new Map())

  const update = useCallback((id: string, patch: Partial<UploadItem>) => {
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)))
  }, [])

  const simulate = useCallback((id: string) => {
    const interval = window.setInterval(() => {
      setItems((prev) =>
        prev.map((item) => {
          if (item.id !== id || item.status !== 'uploading') return item
          return { ...item, progress: Math.min(100, item.progress + 8 + Math.random() * 14) }
        }),
      )
    }, 220)
    uploadTimers.current.set(id, interval)
  }, [])

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
        simulate(id)
      }
    },
    [simulate],
  )

  // Advance uploading -> processing once the simulated transfer fills, then
  // processing -> indexed after a short fixed delay.
  useEffect(() => {
    for (const item of items) {
      if (item.status === 'uploading' && item.progress >= 100) {
        const timer = uploadTimers.current.get(item.id)
        if (timer) {
          window.clearInterval(timer)
          uploadTimers.current.delete(item.id)
        }
        update(item.id, { status: 'processing' })
      }
      if (item.status === 'processing' && !settleTimers.current.has(item.id)) {
        const timeout = window.setTimeout(() => {
          update(item.id, { status: 'indexed' })
          settleTimers.current.delete(item.id)
        }, 900)
        settleTimers.current.set(item.id, timeout)
      }
    }
  }, [items, update])

  useEffect(() => {
    const uploads = uploadTimers.current
    const settles = settleTimers.current
    return () => {
      uploads.forEach((timer) => window.clearInterval(timer))
      settles.forEach((timer) => window.clearTimeout(timer))
    }
  }, [])

  return { items, addFiles }
}
