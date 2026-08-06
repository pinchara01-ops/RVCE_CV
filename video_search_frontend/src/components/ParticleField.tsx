import { useEffect, useRef } from 'react'

interface Particle {
  baseX: number // fraction of width, 0..1
  baseY: number
  ampX: number
  ampY: number
  period: number // drift cycle length in seconds
  phase: number
  radius: number
  opacity: number
}

const PARTICLE_COUNT = 32
const LIGHT_YELLOW = '255,241,181'

function makeParticles(): Particle[] {
  const particles: Particle[] = []
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    particles.push({
      baseX: Math.random(),
      baseY: Math.random(),
      ampX: 0.015 + Math.random() * 0.02,
      ampY: 0.015 + Math.random() * 0.02,
      period: 35 + Math.random() * 25, // slow, 35-60s per drift cycle
      phase: Math.random() * Math.PI * 2,
      radius: 2 + Math.random() * 1.5,
      opacity: 0.35 + Math.random() * 0.3,
    })
  }
  return particles
}

/** Soft, slow-drifting light-yellow glow dots behind the results/pipeline area. */
export function ParticleField() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const parent = canvas?.parentElement
    const ctx = canvas?.getContext('2d')
    if (!canvas || !parent || !ctx) return

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const particles = makeParticles()
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    let raf: number | null = null

    const resize = () => {
      const rect = parent.getBoundingClientRect()
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const draw = (tSeconds: number) => {
      const rect = parent.getBoundingClientRect()
      ctx.clearRect(0, 0, rect.width, rect.height)
      for (const p of particles) {
        const angle = (tSeconds / p.period) * Math.PI * 2 + p.phase
        const x = (p.baseX + Math.sin(angle) * p.ampX) * rect.width
        const y = (p.baseY + Math.cos(angle) * p.ampY) * rect.height

        ctx.beginPath()
        ctx.shadowBlur = 14
        ctx.shadowColor = `rgba(${LIGHT_YELLOW},${Math.min(1, p.opacity * 1.5)})`
        ctx.fillStyle = `rgba(${LIGHT_YELLOW},${p.opacity})`
        ctx.arc(x, y, p.radius, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    if (reducedMotion) {
      draw(0)
    } else {
      const start = performance.now()
      const loop = (now: number) => {
        draw((now - start) / 1000)
        raf = requestAnimationFrame(loop)
      }
      raf = requestAnimationFrame(loop)
    }

    return () => {
      window.removeEventListener('resize', resize)
      if (raf != null) cancelAnimationFrame(raf)
    }
  }, [])

  return <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />
}
