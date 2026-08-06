import { useEffect, useRef } from 'react'

const REMOTE_SRC =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260328_115001_bcdaa3b4-03de-47e7-ad63-ae3e392c32d4.mp4'
const LOCAL_SRC = '/hero.mp4'

// The local copy is gitignored (20 MB), so it exists in development but never
// in a deployment. Choosing by build mode rather than by load failure is
// deliberate: a SPA rewrite answers /hero.mp4 with index.html and HTTP 200, so
// a missing file does not reliably raise an error to fall back from.
const VIDEO_SRC = import.meta.env.DEV ? LOCAL_SRC : REMOTE_SRC

const FADE_IN_MS = 600

/**
 * Full-screen background video. Fades in once on first load, then loops
 * natively (native `loop`) with no per-cycle fade, repeating a fade every
 * few seconds on a short clip reads as the hero flickering in and out.
 */
export function BackgroundVideo() {
  const videoRef = useRef<HTMLVideoElement | null>(null)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    video.style.opacity = '0'
    const startTime = performance.now()
    let raf: number

    const step = (now: number) => {
      const t = Math.min((now - startTime) / FADE_IN_MS, 1)
      video.style.opacity = String(t)
      if (t < 1) raf = requestAnimationFrame(step)
    }

    void video.play().then(() => {
      raf = requestAnimationFrame(step)
    })

    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <video
      ref={videoRef}
      className="absolute inset-0 h-full w-full translate-y-[17%] object-cover"
      src={VIDEO_SRC}
      onError={(event) => {
        // Belt and braces: if the local copy is missing in development, use the
        // CDN rather than showing a black hero.
        const element = event.currentTarget
        if (!element.src.includes('cloudfront')) element.src = REMOTE_SRC
      }}
      muted
      autoPlay
      loop
      playsInline
      preload="auto"
      aria-hidden="true"
    />
  )
}
