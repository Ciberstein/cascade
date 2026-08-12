const STORAGE_KEY = 'cascade.owner'

/**
 * This browser's anonymous identity.
 *
 * There is no login: you arrive and you use it. This token is what tells the
 * server which downloads to show, and it is generated the first time the app
 * opens.
 *
 * It lives in localStorage, so clearing site data loses access to that history
 * - the downloads stay on the server, but without the token there is no way to
 * claim them. Registering an account is exactly that: being able to recover
 * this token from another device.
 */
export function ownerToken(): string {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored) {
    writeCookie(stored)
    return stored
  }

  const token = generate()
  setOwnerToken(token)
  return token
}

/**
 * The same token, also in a cookie.
 *
 * Downloading a file is a browser navigation, and an `<a download>` cannot send
 * headers of its own: without the cookie the server doesn't know whose file it
 * is and answers 400. localStorage stays the source of truth; the cookie is the
 * mirror that navigations do carry.
 */
function writeCookie(token: string): void {
  // SameSite=Strict: the cookie must not travel on requests another site
  // originates, because it is the only credential that exists.
  document.cookie = `cascade_owner=${token}; path=/; max-age=31536000; SameSite=Strict`
}

function generate(): string {
  // crypto rather than Math.random: the token is the only credential there is,
  // and a predictable one would let someone read another person's history by
  // guessing it.
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Adopts an account's token when signing in on another device.
 *
 * It replaces this browser's anonymous token: whatever was downloaded here
 * before signing in stops being visible, because it belongs to the old token.
 */
export function setOwnerToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token)
  writeCookie(token)
}
