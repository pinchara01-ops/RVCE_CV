import { useState } from 'react'
import { Landing } from './pages/Landing'
import { Preprocess } from './pages/Preprocess'
import { HowItWorks } from './pages/HowItWorks'
import { Tests } from './pages/Tests'
import { Developer } from './pages/Developer'
import { Design } from './pages/Design'
import { Onboarding } from './components/Onboarding'
import { usePathname } from './lib/router'
import { hasOnboarded } from './lib/settings'

function App() {
  const pathname = usePathname()
  // Read once on mount: flipping this mid-session would re-open the overlay.
  const [showOnboarding, setShowOnboarding] = useState(() => !hasOnboarded())

  const page = (() => {
    if (pathname === '/preprocess' || pathname === '/upload') return <Preprocess />
    if (pathname === '/how-it-works') return <HowItWorks />
    if (pathname === '/tests') return <Tests />
    if (pathname === '/design') return <Design />
    if (pathname === '/developer') return <Developer />
    return <Landing />
  })()

  return (
    <>
      {page}
      {showOnboarding && <Onboarding onDone={() => setShowOnboarding(false)} />}
    </>
  )
}

export default App
