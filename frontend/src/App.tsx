import { useCallback, useEffect, useState } from 'react'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import { me } from './api/auth'
import './App.css'

function App() {
  // null = the session check hasn't answered yet. Rendering Login during that
  // window would flash the form at users who are already signed in.
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)

  useEffect(() => {
    me()
      .then(() => setIsAuthenticated(true))
      .catch(() => setIsAuthenticated(false))
  }, [])

  // Stable so Dashboard's polling effect isn't torn down on every render.
  const handleUnauthorized = useCallback(() => setIsAuthenticated(false), [])

  if (isAuthenticated === null) return null
  if (!isAuthenticated) return <Login onSuccess={() => setIsAuthenticated(true)} />

  return (
    <div className="app">
      <Dashboard onUnauthorized={handleUnauthorized} />
    </div>
  )
}

export default App
