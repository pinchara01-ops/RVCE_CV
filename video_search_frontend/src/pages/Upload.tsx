import { Nav } from '../components/Nav'
import { BackgroundVideo } from '../components/BackgroundVideo'
import { CameraHero } from '../components/CameraHero'
import { UploadDropzone } from '../components/UploadDropzone'

export function Upload() {
  return (
    <div className="relative min-h-screen bg-black text-paper-100">
      <div className="fixed inset-0 -z-10 overflow-hidden bg-black">
        <BackgroundVideo />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/55 via-black/10 to-black/60" />
      </div>

      <div className="relative z-10 flex min-h-screen flex-col">
        <Nav />

        <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col items-center gap-12 px-6 py-16 md:flex-row md:items-center md:gap-14 md:px-12">
          <div className="flex w-full shrink-0 justify-center md:w-2/5">
            <CameraHero />
          </div>

          <div className="flex w-full flex-col items-center md:w-3/5 md:items-start md:text-left">
            <h1
              className="text-center text-5xl leading-tight tracking-tight text-white md:text-left md:text-6xl"
              style={{ fontFamily: "'Instrument Serif', serif" }}
            >
              Bring your footage <span className="italic text-glow">in</span>
            </h1>
            <p className="mt-4 max-w-lg text-center text-base text-white/70 md:text-left md:text-lg">
              Upload video files to index and search them — MP4, MOV, and AVI supported.
            </p>

            <div className="mt-10 flex w-full justify-center md:justify-start">
              <UploadDropzone />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
