import { useState } from 'react'
import {
  Boxes,
  Cloud,
  Database,
  Film,
  FolderOpen,
  HardDrive,
  Layers,
  Network,
  Server,
} from 'lucide-react'
import { listDriveVideos, SearchApiError, type DriveFile } from '../lib/api'

type Status = 'live' | 'planned'

interface Connector {
  id: string
  name: string
  detail: string
  icon: typeof Database
  status: Status
}

// Only Drive has a backend route today. The rest are declared so the surface is
// visible and each one has an obvious place to be implemented; they are marked
// as not built rather than dressed up as working.
const CONNECTORS: Connector[] = [
  {
    id: 'drive',
    name: 'Google Drive',
    detail: 'Shared folder of videos',
    icon: HardDrive,
    status: 'live',
  },
  {
    id: 'supabase',
    name: 'Supabase',
    detail: 'Postgres + storage bucket',
    icon: Database,
    status: 'planned',
  },
  {
    id: 'qdrant',
    name: 'Qdrant',
    detail: 'Vector collection',
    icon: Layers,
    status: 'planned',
  },
  {
    id: 'pinecone',
    name: 'Pinecone',
    detail: 'Managed vector index',
    icon: Network,
    status: 'planned',
  },
  {
    id: 'weaviate',
    name: 'Weaviate',
    detail: 'Hybrid vector store',
    icon: Boxes,
    status: 'planned',
  },
  {
    id: 's3',
    name: 'S3 bucket',
    detail: 'Object storage prefix',
    icon: Cloud,
    status: 'planned',
  },
  {
    id: 'pgvector',
    name: 'PostgreSQL / pgvector',
    detail: 'Existing relational store',
    icon: Server,
    status: 'planned',
  },
  {
    id: 'local',
    name: 'Local folder',
    detail: 'Path on this machine',
    icon: FolderOpen,
    status: 'planned',
  },
]

interface ConnectorGridProps {
  onError: (message: string | null) => void
}

export function ConnectorGrid({ onError }: ConnectorGridProps) {
  const [active, setActive] = useState<string | null>(null)
  const [folder, setFolder] = useState('')
  const [busy, setBusy] = useState(false)
  const [files, setFiles] = useState<DriveFile[] | null>(null)

  const connect = async () => {
    setBusy(true)
    onError(null)
    try {
      const listing = await listDriveVideos(folder.trim())
      setFiles(listing.files)
    } catch (cause) {
      onError(cause instanceof SearchApiError ? cause.message : 'Could not read that folder.')
      setFiles(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5">
      <p className="text-sm font-medium text-paper-100">Connect a source</p>
      <p className="mt-1 text-xs text-paper-300/50">
        Point the index at footage you already have instead of uploading it.
      </p>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {CONNECTORS.map((connector) => {
          const Icon = connector.icon
          const selected = active === connector.id
          const planned = connector.status === 'planned'
          return (
            <button
              key={connector.id}
              type="button"
              disabled={planned}
              onClick={() => setActive(selected ? null : connector.id)}
              title={planned ? 'Not built yet' : undefined}
              className={`flex flex-col items-start gap-1.5 rounded-xl border p-3 text-left transition-colors ${
                selected
                  ? 'border-glow bg-glow/10'
                  : 'border-white/10 bg-ink-800/60 hover:border-white/25'
              } ${planned ? 'cursor-not-allowed opacity-40' : ''}`}
            >
              <Icon size={16} className={selected ? 'text-glow' : 'text-paper-300/60'} />
              <span className="text-xs font-medium text-paper-100">{connector.name}</span>
              <span className="text-[10px] leading-tight text-paper-300/45">
                {connector.detail}
              </span>
              {planned && (
                <span className="mt-0.5 rounded-full border border-white/10 px-1.5 py-0.5 font-mono text-[9px] text-paper-300/40">
                  not built
                </span>
              )}
            </button>
          )
        })}
      </div>

      {active === 'drive' && (
        <div className="mt-4 rounded-xl border border-white/10 bg-ink-800/40 p-4">
          <p className="text-xs text-paper-300/70">
            Paste a folder link shared as “anyone with the link”.
          </p>
          <div className="mt-2 flex gap-2">
            <input
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
              placeholder="https://drive.google.com/drive/folders/..."
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-ink-900/60 px-3 py-2 text-sm text-paper-100 outline-none placeholder:text-paper-300/30"
            />
            <button
              type="button"
              onClick={connect}
              disabled={busy || !folder.trim()}
              className="shrink-0 rounded-lg border border-white/15 px-4 text-sm text-paper-300/80 transition-colors hover:border-white/30 hover:text-paper-100 disabled:opacity-40"
            >
              {busy ? 'Reading…' : 'Connect'}
            </button>
          </div>

          <p className="mt-2 text-[10px] leading-relaxed text-amber-200/50">
            Needs a Google Cloud project you administer, with the Drive API enabled.
            A key from AI Studio will not work: it belongs to a Google-managed
            project you cannot enable APIs on.
          </p>

          {files && (
            <div className="mt-3 space-y-1.5">
              <p className="font-mono text-[10px] text-paper-300/40">
                {files.length} video{files.length === 1 ? '' : 's'} found
              </p>
              {files.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-2 rounded-lg border border-white/10 bg-ink-900/50 px-3 py-2"
                >
                  <Film size={13} className="shrink-0 text-glow" />
                  <span className="min-w-0 flex-1 truncate text-xs text-paper-100">
                    {item.name}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-paper-300/40">
                    {item.duration_seconds ? `${item.duration_seconds}s` : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
