import { useState } from 'react'
import {
  Boxes,
  Cloud,
  Database,
  Film,
  FolderOpen,
  HardDrive,
  KeyRound,
  Layers,
  Network,
  Server,
} from 'lucide-react'
import { listDriveVideos, SearchApiError, type DriveFile } from '../lib/api'
import { useConnectorField } from '../lib/settings'
import type { Strings } from '../lib/i18n'

interface Field {
  key: string
  label: string
  placeholder: string
  secret?: boolean
}

interface Connector {
  id: string
  name: string
  detail: string
  icon: typeof Database
  /** Only Drive has a backend route; the rest collect credentials only. */
  wired: boolean
  fields: Field[]
}

const CONNECTORS: Connector[] = [
  {
    id: 'drive',
    name: 'Google Drive',
    detail: 'Shared folder of videos',
    icon: HardDrive,
    wired: true,
    fields: [
      { key: 'drive_folder', label: 'Folder link or id', placeholder: 'https://drive.google.com/drive/folders/...' },
      { key: 'drive', label: 'Google API key', placeholder: 'AIza...', secret: true },
    ],
  },
  {
    id: 'supabase',
    name: 'Supabase',
    detail: 'Postgres + storage bucket',
    icon: Database,
    wired: false,
    fields: [
      { key: 'supabase_url', label: 'Project URL', placeholder: 'https://xxxx.supabase.co' },
      { key: 'supabase', label: 'Service role key', placeholder: 'eyJ...', secret: true },
      { key: 'supabase_bucket', label: 'Storage bucket', placeholder: 'videos' },
    ],
  },
  {
    id: 'qdrant',
    name: 'Qdrant',
    detail: 'Vector collection',
    icon: Layers,
    wired: false,
    fields: [
      { key: 'qdrant_url', label: 'Cluster URL', placeholder: 'https://xxxx.qdrant.io:6333' },
      { key: 'qdrant', label: 'API key', placeholder: 'qdr_...', secret: true },
      { key: 'qdrant_collection', label: 'Collection', placeholder: 'video_windows' },
    ],
  },
  {
    id: 'pinecone',
    name: 'Pinecone',
    detail: 'Managed vector index',
    icon: Network,
    wired: false,
    fields: [
      { key: 'pinecone', label: 'API key', placeholder: 'pcsk_...', secret: true },
      { key: 'pinecone_index', label: 'Index name', placeholder: 'video-windows' },
      { key: 'pinecone_env', label: 'Environment', placeholder: 'us-east-1' },
    ],
  },
  {
    id: 'weaviate',
    name: 'Weaviate',
    detail: 'Hybrid vector store',
    icon: Boxes,
    wired: false,
    fields: [
      { key: 'weaviate_url', label: 'Cluster URL', placeholder: 'https://xxxx.weaviate.network' },
      { key: 'weaviate', label: 'API key', placeholder: 'wv_...', secret: true },
      { key: 'weaviate_class', label: 'Class', placeholder: 'VideoWindow' },
    ],
  },
  {
    id: 's3',
    name: 'S3 bucket',
    detail: 'Object storage prefix',
    icon: Cloud,
    wired: false,
    fields: [
      { key: 's3_bucket', label: 'Bucket', placeholder: 'my-footage' },
      { key: 's3_region', label: 'Region', placeholder: 'ap-south-1' },
      { key: 's3_id', label: 'Access key id', placeholder: 'AKIA...' },
      { key: 's3', label: 'Secret access key', placeholder: '••••', secret: true },
    ],
  },
  {
    id: 'pgvector',
    name: 'PostgreSQL / pgvector',
    detail: 'Existing relational store',
    icon: Server,
    wired: false,
    fields: [
      { key: 'pg_url', label: 'Connection string', placeholder: 'postgresql://user@host:5432/db', secret: true },
      { key: 'pg_table', label: 'Table', placeholder: 'video_windows' },
    ],
  },
  {
    id: 'local',
    name: 'Local folder',
    detail: 'Path on this machine',
    icon: FolderOpen,
    wired: false,
    fields: [{ key: 'local_path', label: 'Folder path', placeholder: 'D:\\footage' }],
  },
]

function ConnectorField({ field }: { field: Field }) {
  const [value, setValue] = useConnectorField(field.key)
  return (
    <label className="block">
      <span className="text-[11px] text-paper-300/55">{field.label}</span>
      <div className="mt-1 flex items-center gap-2 rounded-lg border border-white/10 bg-ink-900/60 px-2.5">
        {field.secret && <KeyRound size={12} className="shrink-0 text-paper-300/35" />}
        <input
          type={field.secret ? 'password' : 'text'}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={field.placeholder}
          autoComplete="off"
          spellCheck={false}
          className="min-w-0 flex-1 bg-transparent py-2 text-sm text-paper-100 outline-none placeholder:text-paper-300/25"
        />
      </div>
    </label>
  )
}

interface ConnectorGridProps {
  strings: Strings
  onError: (message: string | null) => void
}

export function ConnectorGrid({ strings: t, onError }: ConnectorGridProps) {
  const [active, setActive] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [files, setFiles] = useState<DriveFile[] | null>(null)
  const [folder] = useConnectorField('drive_folder')

  const selected = CONNECTORS.find((item) => item.id === active) ?? null

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
      <p className="text-sm font-medium text-paper-100">{t.connectSource}</p>
      <p className="mt-1 text-xs text-paper-300/50">{t.connectSourceHint}</p>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {CONNECTORS.map((connector) => {
          const Icon = connector.icon
          const isActive = active === connector.id
          return (
            <button
              key={connector.id}
              type="button"
              onClick={() => setActive(isActive ? null : connector.id)}
              className={`flex flex-col items-start gap-1.5 rounded-xl border p-3 text-left transition-colors ${
                isActive
                  ? 'border-glow bg-glow/10'
                  : 'border-white/10 bg-ink-800/60 hover:border-white/25'
              }`}
            >
              <Icon size={16} className={isActive ? 'text-glow' : 'text-paper-300/60'} />
              <span className="text-xs font-medium text-paper-100">{connector.name}</span>
              <span className="text-[10px] leading-tight text-paper-300/45">
                {connector.detail}
              </span>
              {!connector.wired && (
                <span className="mt-0.5 rounded-full border border-white/10 px-1.5 py-0.5 font-mono text-[9px] text-paper-300/40">
                  {t.notBuilt}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {selected && (
        <div className="mt-4 rounded-xl border border-white/10 bg-ink-800/40 p-4">
          <p className="text-xs font-medium text-paper-100">{selected.name}</p>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {selected.fields.map((field) => (
              <ConnectorField key={field.key} field={field} />
            ))}
          </div>

          {selected.wired ? (
            <>
              <button
                type="button"
                onClick={connect}
                disabled={busy || !folder.trim()}
                className="mt-3 rounded-lg border border-white/15 px-4 py-2 text-sm text-paper-300/80 transition-colors hover:border-white/30 hover:text-paper-100 disabled:opacity-40"
              >
                {busy ? '…' : 'Connect'}
              </button>
              <p className="mt-2 text-[10px] leading-relaxed text-amber-200/50">{t.driveWarning}</p>
            </>
          ) : (
            <p className="mt-3 text-[10px] leading-relaxed text-paper-300/40">
              Credentials are stored for this tab only. This connector has no backend route yet, so
              nothing is sent anywhere.
            </p>
          )}

          {files && (
            <div className="mt-3 space-y-1.5">
              <p className="font-mono text-[10px] text-paper-300/40">
                {files.length} {t.videosFound}
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
