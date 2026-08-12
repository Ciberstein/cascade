import { afterEach, beforeEach, expect, test } from 'vitest'
import { ownerToken, setOwnerToken } from './owner'

beforeEach(() => {
  localStorage.clear()
  document.cookie = 'cascade_owner=; path=/; max-age=0'
})

afterEach(() => localStorage.clear())

test('the token is mirrored into a cookie', () => {
  const token = ownerToken()

  // Un <a download> no puede mandar cabeceras: sin la cookie el servidor
  // responde 400 y el navegador muestra "error desconocido en el servidor".
  expect(document.cookie).toContain(`cascade_owner=${token}`)
})

test('the same token comes back on a second call', () => {
  expect(ownerToken()).toBe(ownerToken())
})

test('adopting an account token updates the cookie too', () => {
  setOwnerToken('cuenta0000000000000000000000000a')

  expect(document.cookie).toContain('cascade_owner=cuenta0000000000000000000000000a')
})

test('a token already in storage still refreshes the cookie', () => {
  // Quien ya venía usando Cascade antes de que existiera la cookie no tiene
  // que borrar sus datos para que las descargas funcionen.
  localStorage.setItem('cascade.owner', 'viejo00000000000000000000000000a')

  ownerToken()

  expect(document.cookie).toContain('cascade_owner=viejo00000000000000000000000000a')
})
