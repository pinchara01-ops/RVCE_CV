import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Film, ImageIcon, Mic, Paperclip, Square, X } from 'lucide-react'
import { useRecorder, Waveform, type Recording } from './VoiceRecorder'
import type { Strings } from '../lib/i18n'

export interface Attachments {
  images: File[]
  reference: File | null
}

export const EMPTY_ATTACHMENTS: Attachments = { images: [], reference: null }

interface QueryComposerProps {
  strings: Strings
  value: string
  onChange: (value: string) => void
  recording: Recording | null
  onRecorded: (recording: Recording | null) => void
  attachments: Attachments
  onAttachments: (attachments: Attachments) => void
  disabled: boolean
  onSubmit: () => void
  onError: (message: string) => void
  rtl: boolean
}

/**
 * One input carrying every modality the search accepts: typed text, a spoken
 * request, reference images, and a reference clip. They are submitted together
 * as a single request rather than as separate searches.
 */
export function QueryComposer({
  strings,
  value,
  onChange,
  recording,
  onRecorded,
  attachments,
  onAttachments,
  disabled,
  onSubmit,
  onError,
  rtl,
}: QueryComposerProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const imageInput = useRef<HTMLInputElement>(null)
  const referenceInput = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const addImages = (picked: File[]) => {
    const images = picked.filter((item) => item.type.startsWith('image/'))
    if (!images.length) return
    onAttachments({ ...attachments, images: [...attachments.images, ...images].slice(0, 4) })
  }

  // Opening the picker is deferred so the menu's state update settles first;
  // clicking a hidden input mid-render can be swallowed.
  const openPicker = (ref: React.RefObject<HTMLInputElement | null>) => {
    setMenuOpen(false)
    window.setTimeout(() => ref.current?.click(), 0)
  }

  // Paste an image straight into the composer: the usual way someone supplies
  // "find this person" from a screenshot.
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (disabled) return
      const files = Array.from(event.clipboardData?.files ?? [])
      const images = files.filter((file) => file.type.startsWith('image/'))
      if (images.length) {
        event.preventDefault()
        addImages(images)
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  })

  const { state, livePeaks, start, stop } = useRecorder(onRecorded, onError)
  const isRecording = state === 'recording'

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [menuOpen])

  const hasAttachments =
    attachments.images.length > 0 || attachments.reference !== null || recording !== null
  const canSubmit = !disabled && (Boolean(value.trim()) || hasAttachments)

  const removeImage = (index: number) =>
    onAttachments({
      ...attachments,
      images: attachments.images.filter((_, position) => position !== index),
    })

  return (
    <div className="mx-auto w-full max-w-xl">
      {hasAttachments && (
        <div className="mb-2 flex flex-wrap gap-2">
          {recording && (
            <span className="flex items-center gap-2 rounded-full border border-glow/40 bg-glow/10 py-1 pl-3 pr-1 text-xs text-paper-100">
              <Mic size={12} className="text-glow" />
              {strings.spokenRequest} · {recording.seconds.toFixed(1)}s
              <button
                type="button"
                onClick={() => onRecorded(null)}
                aria-label={strings.discardRecording}
                className="rounded-full p-1 text-white/50 transition-colors hover:text-white"
              >
                <X size={12} />
              </button>
            </span>
          )}
          {attachments.images.map((image, index) => (
            <span
              key={`${image.name}-${index}`}
              className="flex items-center gap-2 rounded-full border border-white/15 bg-ink-800/70 py-1 pl-3 pr-1 text-xs text-paper-100"
            >
              <ImageIcon size={12} className="text-glow" />
              <span className="max-w-[10rem] truncate">{image.name}</span>
              <button
                type="button"
                onClick={() => removeImage(index)}
                aria-label="Remove image"
                className="rounded-full p-1 text-white/50 transition-colors hover:text-white"
              >
                <X size={12} />
              </button>
            </span>
          ))}
          {attachments.reference && (
            <span className="flex items-center gap-2 rounded-full border border-white/15 bg-ink-800/70 py-1 pl-3 pr-1 text-xs text-paper-100">
              <Film size={12} className="text-glow" />
              <span className="max-w-[10rem] truncate">{attachments.reference.name}</span>
              <button
                type="button"
                onClick={() => onAttachments({ ...attachments, reference: null })}
                aria-label="Remove reference clip"
                className="rounded-full p-1 text-white/50 transition-colors hover:text-white"
              >
                <X size={12} />
              </button>
            </span>
          )}
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (canSubmit) onSubmit()
        }}
        onDragOver={(event) => {
          event.preventDefault()
          setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragActive(false)
          const dropped = Array.from(event.dataTransfer.files ?? [])
          addImages(dropped)
          const clip = dropped.find((file) => file.type.startsWith('video/'))
          if (clip) onAttachments({ ...attachments, reference: clip })
        }}
        className={`liquid-glass flex w-full items-center gap-2 rounded-full py-2 pl-3 pr-2 transition-colors ${
          dragActive ? 'ring-1 ring-glow' : ''
        }`}
        dir={rtl ? 'rtl' : 'ltr'}
      >
        <div className="relative shrink-0" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            disabled={disabled || isRecording}
            aria-label="Add attachment"
            className="flex items-center justify-center rounded-full p-2.5 text-white/70 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
          >
            <Paperclip size={18} />
          </button>

          {menuOpen && (
            <div className="absolute bottom-full left-0 z-30 mb-2 w-56 overflow-hidden rounded-xl border border-white/10 bg-ink-900/95 p-1 shadow-xl backdrop-blur">
              <button
                type="button"
                onClick={() => openPicker(imageInput)}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-paper-300/80 transition-colors hover:bg-white/5 hover:text-paper-100"
              >
                <ImageIcon size={15} className="shrink-0 text-glow" />
                <span>
                  Reference image
                  <span className="block text-[11px] text-paper-300/40">Find this person or object</span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => openPicker(referenceInput)}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-paper-300/80 transition-colors hover:bg-white/5 hover:text-paper-100"
              >
                <Film size={15} className="shrink-0 text-glow" />
                <span>
                  Reference clip
                  <span className="block text-[11px] text-paper-300/40">Find moments like this</span>
                </span>
              </button>
            </div>
          )}
        </div>

        {isRecording ? (
          <>
            <Waveform peaks={livePeaks} live />
            <span className="shrink-0 font-mono text-xs text-red-300">rec</span>
          </>
        ) : (
          <input
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={strings.placeholder}
            disabled={disabled}
            className="min-w-0 flex-1 bg-transparent text-base text-white outline-none placeholder:text-white/40"
            aria-label={strings.searchAria}
          />
        )}

        <button
          type="button"
          onClick={isRecording ? stop : () => void start()}
          disabled={disabled}
          aria-label={isRecording ? strings.stopRecording : strings.askByVoice}
          title={isRecording ? strings.stopRecording : strings.askByVoice}
          className={`flex shrink-0 items-center justify-center rounded-full p-2.5 transition-colors disabled:opacity-40 ${
            isRecording ? 'bg-red-500/90 text-white' : 'text-white/70 hover:bg-white/10 hover:text-white'
          }`}
        >
          {isRecording ? <Square size={18} fill="currentColor" /> : <Mic size={18} />}
        </button>

        <button
          type="submit"
          disabled={!canSubmit}
          aria-label={strings.runSearch}
          className="flex shrink-0 items-center justify-center rounded-full bg-white p-3 text-black transition-opacity disabled:opacity-40"
        >
          <ArrowRight size={20} className={rtl ? 'rotate-180' : undefined} />
        </button>
      </form>

      <input
        ref={imageInput}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(event) => {
          addImages(Array.from(event.target.files ?? []))
          event.target.value = ''
        }}
      />
      <input
        ref={referenceInput}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(event) => {
          const picked = event.target.files?.[0] ?? null
          if (picked) onAttachments({ ...attachments, reference: picked })
          event.target.value = ''
        }}
      />
    </div>
  )
}
