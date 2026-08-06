import { Landing } from './pages/Landing'
import { Preprocess } from './pages/Preprocess'
import { HowItWorks } from './pages/HowItWorks'
import { Tests } from './pages/Tests'
import { Developer } from './pages/Developer'
import { usePathname } from './lib/router'

function App() {
  const pathname = usePathname()

  if (pathname === '/preprocess' || pathname === '/upload') return <Preprocess />
  if (pathname === '/how-it-works') return <HowItWorks />
  if (pathname === '/tests') return <Tests />
  if (pathname === '/developer') return <Developer />
  return <Landing />
}

export default App
