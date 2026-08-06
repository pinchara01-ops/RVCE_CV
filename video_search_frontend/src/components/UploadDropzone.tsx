import { useRef, useState } from 'react'
import { UploadCloud } from 'lucide-react'
import { useUploads } from '../lib/uploads'
import { UploadFileRow } from './UploadFileRow'

export function UploadDropzone() {
  const { items, addFiles } = useUploads()
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div className="w-full max-w-3xl">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragActive(false)
          if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
        }}
        className={`liquid-glass flex cursor-pointer flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed bg-ink-900/50 px-8 py-20 text-center transition-colors ${
          dragActive ? 'border-glow' : 'border-white/15'
        }`}
      >
        <UploadCloud size={40} className={dragActive ? 'text-glow' : 'text-paper-300/50'} />
        <p className="text-base text-paper-100">Drag and drop videos here, or click to browse</p>
        <p className="text-sm text-paper-300/40">MP4, MOV, AVI · up to 2GB per file</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".mp4,.mov,.avi,video/mp4,video/quicktime,video/x-msvideo"
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) addFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {items.length > 0 && (
        <div className="mt-4 space-y-2">
          {items.map((item) => (
            <UploadFileRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
