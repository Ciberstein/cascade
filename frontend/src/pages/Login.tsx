import { useState } from 'react'
import { login } from '../api/auth'
import './Login.css'

interface Props {
  onSuccess: () => void
}

export default function Login({ onSuccess }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username, password)
      onSuccess()
    } catch {
      // Every failure reads the same to the user by design: distinguishing
      // "no such user" from "wrong password" would confirm which usernames
      // exist. There is only one account anyway.
      setError('Usuario o contraseña incorrectos')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login">
      <form className="login__form" onSubmit={handleSubmit}>
        <h1 className="login__title">Cascade</h1>

        <div className="login__field">
          <label htmlFor="username">Usuario</label>
          <input
            id="username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>

        <div className="login__field">
          <label htmlFor="password">Contraseña</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button type="submit" disabled={submitting}>
          Ingresar
        </button>

        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}
      </form>
    </main>
  )
}
