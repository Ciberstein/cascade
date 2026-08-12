import { useEffect, useState } from 'react'
import { getAccount, login, register } from '../api/account'
import Masthead from '../components/Masthead'
import './Account.css'

interface Props {
  onClose: () => void
  /** Called after signing in: the list becomes that account's. */
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
      setError(e instanceof Error ? e.message : 'Could not complete that')
    } finally {
      setBusy(false)
    }
  }

  if (registeredAs) {
    return (
      <>
        <Masthead>
          <button onClick={onClose}>Back</button>
        </Masthead>

        <h1 className="account__title">Account</h1>
        <p className="account__who">
          This browser is registered as <span className="account__name">{registeredAs}</span>.
        </p>
        <p className="account__lede">
          To see this same list on another device, sign in there with your username and password.
        </p>
      </>
    )
  }

  return (
    <>
      <Masthead>
        <button onClick={onClose}>Back</button>
      </Masthead>

      <h1 className="account__title">Account (optional)</h1>
      <p className="account__lede">
        Cascade works without an account. Your download list lives in this browser; clearing site
        data loses access to it. Register only if you want to keep that list and see it from another
        device.
      </p>

      <div className="account__form">
        <div className="account__field">
          <label className="eyebrow" htmlFor="account-user">
            Username
          </label>
          <input id="account-user" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>

        <div className="account__field">
          <label className="eyebrow" htmlFor="account-pass">
            Password
          </label>
          <input
            id="account-pass"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {error && (
          <p className="notice" role="alert">
            {error}
          </p>
        )}

        <div className="account__actions">
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                // Keeps the current list: registering ties this browser's token
                // to the account, it does not start a new list.
                const account = await register(username, password)
                setRegisteredAs(account.username)
              })
            }
          >
            Register and keep this list
          </button>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await login(username, password)
                onIdentityChanged()
              })
            }
          >
            Sign in and bring my list
          </button>
        </div>
      </div>
    </>
  )
}
