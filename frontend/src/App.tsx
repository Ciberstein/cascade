import Dashboard from './pages/Dashboard'
import './App.css'

/**
 * Sin pantalla de login: se entra y se usa.
 *
 * La identidad de este navegador es un token anónimo en localStorage (ver
 * api/owner.ts), que el cliente manda en cada request. No hay nada que
 * esperar antes de renderizar, así que tampoco hay estado de "verificando
 * sesión" ni parpadeo de formulario.
 */
function App() {
  return (
    <div className="app">
      <Dashboard />
    </div>
  )
}

export default App
