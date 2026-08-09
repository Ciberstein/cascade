import { useEffect, useState } from 'react'
import { getAccount, login, register } from '../api/account'
import './Account.css'

interface Props {
  onClose: () => void
  /** Se llama tras iniciar sesión: la lista pasa a ser la de esa cuenta. */
  onIdentityChanged: () => void
}

export default function Account({ onClose, onIdentityChanged }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [registeredAs, setRegisteredAs] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getAccount()
      .then((a) => setRegisteredAs(a.username))
      .catch(() => setRegisteredAs(null))
  }, [])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo completar la operación')
    } finally {
      setBusy(false)
    }
  }

  if (registeredAs) {
    return (
      <div className="account">
        <div className="account__header">
          <button onClick={onClose}>Volver</button>
        </div>
        <h1 className="account__title">Cuenta</h1>
        <p>
          Este navegador está registrado como <strong>{registeredAs}</strong>.
        </p>
        <p className="account__hint">
          Para ver esta misma lista en otro dispositivo, entrá ahí con tu usuario y contraseña.
        </p>
      </div>
    )
  }

  return (
    <div className="account">
      <div className="account__header">
        <button onClick={onClose}>Volver</button>
      </div>

      <h1 className="account__title">Cuenta (opcional)</h1>
      <p className="account__hint">
        Cascade funciona sin registrarse. Tu lista de descargas vive en este navegador; si borrás los
        datos del sitio, se pierde el acceso a ella. Registrate solo si querés conservarla y verla
        desde otro dispositivo.
      </p>

      <div className="account__field">
        <label htmlFor="account-user">Usuario</label>
        <input id="account-user" value={username} onChange={(e) => setUsername(e.target.value)} />
      </div>

      <div className="account__field">
        <label htmlFor="account-pass">Contraseña</label>
        <input
          id="account-pass"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>

      {error && (
        <p className="account__error" role="alert">
          {error}
        </p>
      )}

      <div className="account__actions">
        <button
          disabled={busy}
          onClick={() =>
            void run(async () => {
              // Conserva la lista actual: registrarse ata el token de este
              // navegador a la cuenta, no crea una lista nueva.
              const account = await register(username, password)
              setRegisteredAs(account.username)
            })
          }
        >
          Registrarme y conservar esta lista
        </button>
        <button
          className="account__primary"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await login(username, password)
              onIdentityChanged()
            })
          }
        >
          Entrar y traer mi lista
        </button>
      </div>
    </div>
  )
}
