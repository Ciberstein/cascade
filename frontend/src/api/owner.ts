const STORAGE_KEY = 'cascade.owner'

/**
 * Identidad anónima de este navegador.
 *
 * No hay login: se entra y se usa. Este token es lo que le dice al servidor
 * qué descargas mostrar, y se genera la primera vez que se abre la app.
 *
 * Vive en localStorage, así que borrar los datos del sitio hace perder el
 * acceso a ese historial - las descargas siguen en el servidor, pero sin el
 * token no hay forma de reclamarlas. Registrar una cuenta, cuando exista, va a
 * ser justamente eso: poder recuperar este token desde otro dispositivo.
 */
export function ownerToken(): string {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored) return stored

  const token = generate()
  localStorage.setItem(STORAGE_KEY, token)
  return token
}

function generate(): string {
  // crypto y no Math.random: el token es la única credencial que hay, y uno
  // predecible dejaría leer el historial ajeno adivinándolo.
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
}
