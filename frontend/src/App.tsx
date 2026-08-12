import Dashboard from './pages/Dashboard'
import './App.css'

/**
 * No login screen: you arrive and you use it.
 *
 * This browser's identity is an anonymous token in localStorage (see
 * api/owner.ts), which the client sends on every request. There is nothing to
 * wait for before rendering, so there is no "checking session" state and no
 * flash of a login form.
 */
function App() {
  return (
    <div className="app">
      <Dashboard />
    </div>
  )
}

export default App
