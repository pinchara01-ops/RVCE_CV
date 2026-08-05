import { Landing } from './pages/Landing'
import { Upload } from './pages/Upload'
import { usePathname } from './lib/router'

function App() {
  const pathname = usePathname()

  if (pathname === '/upload') return <Upload />
  return <Landing />
}

export default App
