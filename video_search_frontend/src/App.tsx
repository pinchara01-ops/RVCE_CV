import { Landing } from './pages/Landing'
import { Preprocess } from './pages/Preprocess'
import { HowItWorks } from './pages/HowItWorks'
import { Tests } from './pages/Tests'
import { Developer } from './pages/Developer'
import { Design } from './pages/Design'
import { usePathname } from './lib/router'

function App() {
  const pathname = usePathname()
  const page = (() => {
    if (pathname === '/preprocess' || pathname === '/upload') return <Preprocess />
    if (pathname === '/how-it-works') return <HowItWorks />
    if (pathname === '/tests') return <Tests />
    if (pathname === '/design') return <Design />
    if (pathname === '/developer') return <Developer />
    return <Landing />
  })()

  return page
}

export default App
