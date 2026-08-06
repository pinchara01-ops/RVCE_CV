import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import type { UploadItem } from '../lib/uploads'
import { formatBytes } from '../lib/format'
import { LinearProgress } from './LinearProgress'

export function UploadFileRow({ item }: { item: UploadItem }) {
  return (
    <div className="liquid-glass rounded-xl border border-white/10 bg-ink-900/60 p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0 truncate text-sm text-paper-100">{item.name}</span>
        <span className="shrink-0 font-mono text-xs text-paper-300/45">{formatBytes(item.size)}</span>
      </div>

      <div className="mt-2 flex items-center gap-3">
        {item.status === 'failed' ? (
          <div className="flex items-center gap-1.5 text-xs text-red-300/80">
            <AlertTriangle size={13} />
            {item.error ?? 'Upload failed'}
          </div>
        ) : (
          <>
            <div className="flex-1">
              <LinearProgress percent={item.status === 'indexed' ? 100 : item.progress} />
            </div>
            <div className="flex w-24 shrink-0 items-center justify-end gap-1.5 text-xs">
              {item.status === 'uploading' && (
                <>
                  <Loader2 size={12} className="animate-spin text-paper-300/60" />
                  <span className="text-paper-300/60">{Math.round(item.progress)}%</span>
                </>
              )}
              {item.status === 'processing' && (
                <>
                  <Loader2 size={12} className="animate-spin text-glow" />
                  <span className="text-paper-300/60">Processing {Math.round(item.progress)}%</span>
                </>
              )}
              {item.status === 'indexed' && (
                <>
                  <CheckCircle2 size={13} className="text-glow" />
                  <span className="text-glow">Indexed</span>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
