import { useEffect, useRef } from 'react'

const VIDEO_SRC =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260328_115001_bcdaa3b4-03de-47e7-ad63-ae3e392c32d4.mp4'

const FADE_IN_MS = 600

/**
 * Full-screen background video. Fades in once on first load, then loops
 * natively (native `loop`) with no per-cycle fade — repeating a fade every
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
      muted
      autoPlay
      loop
      playsInline
      preload="auto"
      aria-hidden="true"
    />
  )
}
