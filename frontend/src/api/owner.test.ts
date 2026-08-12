import { afterEach, beforeEach, expect, test } from 'vitest'
import { ownerToken, setOwnerToken } from './owner'

beforeEach(() => {
  localStorage.clear()
  document.cookie = 'cascade_owner=; path=/; max-age=0'
})

afterEach(() => localStorage.clear())

test('the token is mirrored into a cookie', () => {
  const token = ownerToken()

  // An <a download> cannot send headers: without the cookie the server
  // answers 400 and the browser shows an unexplained server error.
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
  // Anyone already using Cascade before the cookie existed shouldn't have to
  // clear their data to make downloads work.
  localStorage.setItem('cascade.owner', 'viejo00000000000000000000000000a')

  ownerToken()

  expect(document.cookie).toContain('cascade_owner=viejo00000000000000000000000000a')
})
