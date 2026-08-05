import { useEffect, useRef } from 'react'

const VIDEO_SRC =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260328_115001_bcdaa3b4-03de-47e7-ad63-ae3e392c32d4.mp4'

const FADE_MS = 500
const FADE_OUT_LEAD_SECONDS = 0.55

/**
 * Full-screen looping background video with a hand-rolled fade system
 * (no CSS transitions): fades in on load/loop start, fades out just before
 * the clip ends, then resets and fades back in — so the loop point never
 * shows a visible cut or a frozen last frame.
 */
export function BackgroundVideo() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const fadingOutRef = useRef(false)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const fadeTo = (target: number, duration = FADE_MS) => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      const start = parseFloat(video.style.opacity || '1')
      const startTime = performance.now()
      const step = (now: number) => {
        const t = Math.min((now - startTime) / duration, 1)
        video.style.opacity = String(start + (target - start) * t)
        if (t < 1) {
          rafRef.current = requestAnimationFrame(step)
        } else {
          rafRef.current = null
        }
      }
      rafRef.current = requestAnimationFrame(step)
    }

    const handleTimeUpdate = () => {
      if (
        !fadingOutRef.current &&
        video.duration &&
        video.duration - video.currentTime <= FADE_OUT_LEAD_SECONDS
      ) {
        fadingOutRef.current = true
        fadeTo(0)
      }
    }

    const handleEnded = () => {
      video.style.opacity = '0'
      window.setTimeout(() => {
        video.currentTime = 0
        void video.play()
        fadingOutRef.current = false
        fadeTo(1)
      }, 100)
    }

    video.style.opacity = '0'
    video.addEventListener('timeupdate', handleTimeUpdate)
    video.addEventListener('ended', handleEnded)
    void video.play().then(() => fadeTo(1))

    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate)
      video.removeEventListener('ended', handleEnded)
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  return (
    <video
      ref={videoRef}
      className="absolute inset-0 h-full w-full translate-y-[17%] object-cover"
      src={VIDEO_SRC}
      muted
      autoPlay
      playsInline
      preload="auto"
      aria-hidden="true"
    />
  )
}
