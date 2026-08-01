import { useRef, useState } from 'react'
import { IconVideo, IconCircleCheck } from '@tabler/icons-react'
import './UploadDropzone.css'

const ACCEPTED_TYPES = ['video/mp4', 'video/quicktime']

export default function UploadDropzone({ onReady }) {
  const [isDragOver, setIsDragOver] = useState(false)
  const [fileName, setFileName] = useState(null)
  const [status, setStatus] = useState('idle') // idle | processing | ready
  const inputRef = useRef(null)

  function acceptFile(file) {
    if (!file) return
    setFileName(file.name)
    setStatus('processing')

    // Frontend-only build: no real backend processing pipeline is wired
    // here yet (that's the Processing/Indexing teammate's module). This
    // just simulates the "indexing this clip" delay before the search bar
    // appears, so the flow reads correctly for a demo.
    setTimeout(() => {
      setStatus('ready')
      onReady?.(file)
    }, 1300)
  }

  function handleDrop(e) {
    e.preventDefault()
    setIsDragOver(false)
    acceptFile(e.dataTransfer.files?.[0])
  }

  function handleBrowseClick() {
    inputRef.current?.click()
  }

  return (
    <div className="dropzone-wrap">
      {/* Scattered "index card" decorations - real accent-colored blocks
          with visible borders and their own mono labels, not a shadow-
          colored duplicate of the main box. */}
      <div className="dropzone-decor dropzone-decor--rust" aria-hidden="true">
        <span className="dropzone-decor__label font-mono">reel_014</span>
      </div>
      <div className="dropzone-decor dropzone-decor--mustard" aria-hidden="true">
        <span className="dropzone-decor__label font-mono">cam_02</span>
      </div>
      <div className="dropzone-decor dropzone-decor--olive" aria-hidden="true">
        <span className="dropzone-decor__label font-mono">aud_07</span>
      </div>

      <div
        className={`dropzone${isDragOver ? ' dropzone--drag' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={handleBrowseClick}
        role="button"
        tabIndex={0}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(',')}
          hidden
          onChange={(e) => acceptFile(e.target.files?.[0])}
        />

        {status === 'idle' && (
          <>
            <IconVideo size={60} stroke={1.2} color="var(--color-rust)" />
            <p className="dropzone__label">Drop a video here or click to browse</p>
            <p className="dropzone__sub">
              We'll index every frame, sound, and word spoken — then you can search it like text.
            </p>
            <p className="dropzone__hint font-mono">MP4, MOV — up to 2GB</p>
          </>
        )}

        {status === 'processing' && (
          <>
            <div className="dropzone__spinner" aria-hidden="true" />
            <p className="dropzone__label">{fileName}</p>
            <p className="dropzone__sub">Indexing visual, audio, and speech signal…</p>
            <p className="dropzone__hint font-mono">indexing clip…</p>
          </>
        )}

        {status === 'ready' && (
          <>
            <IconCircleCheck size={60} stroke={1.2} color="var(--color-olive)" />
            <p className="dropzone__label">{fileName}</p>
            <p className="dropzone__sub">Indexed and ready — search below.</p>
            <p className="dropzone__hint font-mono">ready to search</p>
          </>
        )}
      </div>
    </div>
  )
}
