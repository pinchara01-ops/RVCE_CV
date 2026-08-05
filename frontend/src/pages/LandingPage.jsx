import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { IconAperture, IconWaveSine, IconMicrophone, IconEye, IconMovie } from '@tabler/icons-react'
import UploadDropzone from '../components/UploadDropzone.jsx'
import SearchBar from '../components/SearchBar.jsx'
import './LandingPage.css'

export default function LandingPage() {
  const [isReady, setIsReady] = useState(false)
  const navigate = useNavigate()

  function handleSearch(query) {
    navigate(`/results?q=${encodeURIComponent(query)}`)
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="wordmark">archival</span>
        <span className="subtitle">multimodal video search</span>
      </header>

      <main className="landing-main">
        {/* Scattered marks + thin flourish lines - purely decorative, low
            opacity, so the page reads as composed rather than a single
            box floating on blank canvas. */}
        <IconEye className="landing-mark landing-mark--eye" stroke={1} aria-hidden="true" />
        <IconWaveSine className="landing-mark landing-mark--wave" stroke={1} aria-hidden="true" />
        <IconMicrophone className="landing-mark landing-mark--mic" stroke={1} aria-hidden="true" />
        <IconAperture className="landing-mark landing-mark--aperture" stroke={1} aria-hidden="true" />
        <IconMovie className="landing-mark landing-mark--movie" stroke={1} aria-hidden="true" />
        <span className="landing-line landing-line--a" aria-hidden="true" />
        <span className="landing-line landing-line--b" aria-hidden="true" />

        <div className="landing-intro">
          <span className="eyebrow">visual · audio · speech · caption</span>
          <h1>Search your footage like it's text</h1>
          <p className="landing-intro__lede">
            Describe a moment — “someone drops a bag near the entrance” — and archival finds it
            across every frame, sound, and word spoken.
          </p>
        </div>

        <UploadDropzone onReady={() => setIsReady(true)} />

        {isReady && (
          <div className="landing-search">
            <SearchBar onSearch={handleSearch} autoFocus />
          </div>
        )}
      </main>

      <footer className="app-footer">qdrant + rrf fusion</footer>
    </div>
  )
}
