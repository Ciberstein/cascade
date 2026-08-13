import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Settings from './Settings'
import * as settingsApi from '../api/settings'
import type { AppSettings } from '../types'

afterEach(() => vi.restoreAllMocks())

const saved: AppSettings = {
  max_concurrent_downloads: 3,
  chunks_per_file: 4,
  max_speed_kbps: 0,
  max_concurrent_crawls: 5,
}

test('loads existing settings and submits updates', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue(saved)
  const updateSpy = vi
    .spyOn(settingsApi, 'updateSettings')
    .mockResolvedValue({ ...saved, max_concurrent_downloads: 5 })

  render(<Settings onClose={() => {}} />)

  await waitFor(() => expect(screen.getByLabelText('Simultaneous downloads')).toHaveValue(3))

  fireEvent.change(screen.getByLabelText('Simultaneous downloads'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(updateSpy).toHaveBeenCalledWith({ ...saved, max_concurrent_downloads: 5 }))
})

test('closes only after the save succeeds', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue(saved)
  vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue(saved)
  const onClose = vi.fn()

  render(<Settings onClose={onClose} />)
  await screen.findByLabelText('Simultaneous downloads')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(onClose).toHaveBeenCalled())
})

test('keeps the form open and shows why when the save is rejected', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue(saved)
  vi.spyOn(settingsApi, 'updateSettings').mockRejectedValue(new Error('chunks_per_file: must be <= 16'))
  const onClose = vi.fn()

  render(<Settings onClose={onClose} />)
  await screen.findByLabelText('Chunks per file')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByText('chunks_per_file: must be <= 16')).toBeInTheDocument()
  expect(onClose).not.toHaveBeenCalled()
})

test('does not send a half-typed number field as 0', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue(saved)
  const updateSpy = vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue(saved)

  render(<Settings onClose={() => {}} />)
  await screen.findByLabelText('Simultaneous downloads')

  // Clearing the field to retype it makes value '' -> Number('') is 0, which
  // the API rejects (ge=1). Saving must not silently submit that.
  fireEvent.change(screen.getByLabelText('Simultaneous downloads'), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  expect(updateSpy).not.toHaveBeenCalled()
})

test('saves the crawl concurrency limit', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue(saved)
  const updateSpy = vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue(saved)

  render(<Settings onClose={() => {}} />)
  await waitFor(() => expect(screen.getByLabelText('Simultaneous checks')).toHaveValue(5))

  fireEvent.change(screen.getByLabelText('Simultaneous checks'), { target: { value: '8' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() =>
    expect(updateSpy).toHaveBeenCalledWith({ ...saved, max_concurrent_crawls: 8 }),
  )
})

test('saving the numbers does not wipe a stored cookie jar', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue({
    max_concurrent_downloads: 3, chunks_per_file: 4, max_speed_kbps: 0,
    max_concurrent_crawls: 5, has_cookies: true,
  })
  const update = vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue({
    max_concurrent_downloads: 3, chunks_per_file: 4, max_speed_kbps: 0, max_concurrent_crawls: 5,
  })

  render(<Settings onClose={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Save' }))

  // The screen never shows the jar, so it cannot send it back. Omitting the
  // field is what tells the API to leave the stored one alone.
  await waitFor(() => expect(update).toHaveBeenCalled())
  expect(update.mock.calls[0][0]).not.toHaveProperty('hoster_cookies')
})

test('a pasted jar is sent and the stored one is never displayed', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue({
    max_concurrent_downloads: 3, chunks_per_file: 4, max_speed_kbps: 0,
    max_concurrent_crawls: 5, has_cookies: true,
  })
  const update = vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue({
    max_concurrent_downloads: 3, chunks_per_file: 4, max_speed_kbps: 0, max_concurrent_crawls: 5,
  })

  render(<Settings onClose={vi.fn()} />)
  const jar = await screen.findByLabelText('Cookies for blocked sites')

  // A live credential: returning it would hand every visitor the account.
  expect(jar).toHaveValue('')

  fireEvent.change(jar, { target: { value: '# Netscape HTTP Cookie File' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() =>
    expect(update.mock.calls[0][0]).toMatchObject({
      hoster_cookies: '# Netscape HTTP Cookie File',
    }),
  )
})
