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
  if (stored) {
    writeCookie(stored)
    return stored
  }

  const token = generate()
  setOwnerToken(token)
  return token
}

/**
 * El mismo token, también en cookie.
 *
 * Descargar un archivo es una navegación del navegador, y un `<a download>` no
 * puede mandar cabeceras propias: sin la cookie el servidor no sabe de quién es
 * el archivo y responde 400. localStorage sigue siendo la fuente de verdad; la
 * cookie es el reflejo que las navegaciones sí llevan.
 */
function writeCookie(token: string): void {
  // SameSite=Strict: la cookie no debe viajar en pedidos que origine otro
  // sitio, porque es la única credencial que existe.
  document.cookie = `cascade_owner=${token}; path=/; max-age=31536000; SameSite=Strict`
}

function generate(): string {
  // crypto y no Math.random: el token es la única credencial que hay, y uno
  // predecible dejaría leer el historial ajeno adivinándolo.
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Adopta el token de una cuenta al iniciar sesión en otro dispositivo.
 *
 * Reemplaza el token anónimo de este navegador: lo que se hubiera descargado
 * acá antes de iniciar sesión deja de verse, porque pertenece al token viejo.
 */
export function setOwnerToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token)
  writeCookie(token)
}
