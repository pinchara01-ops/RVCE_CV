import { Landing } from './pages/Landing'
import { Upload } from './pages/Upload'
import { Tests } from './pages/Tests'
import { usePathname } from './lib/router'

function App() {
  const pathname = usePathname()

  if (pathname === '/upload') return <Upload />
  if (pathname === '/tests') return <Tests />
  return <Landing />
}

export default App
