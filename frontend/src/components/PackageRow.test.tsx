import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import PackageRow from './PackageRow'
import type { Package } from '../types'

const pkg: Package = {
  id: 'pkg-1',
  name: 'My package',
  status: 'running',
  target_dir: '/downloads/my-package',
  items: [
    {
      id: 'i1',
      url: 'https://x/a.zip',
      filename: 'a.zip',
      status: 'running',
      total_size: 1000,
      downloaded_bytes: 400,
      error_message: null,
      hoster: 'direct',
      retry_after: null,
    },
    {
      id: 'i2',
      url: 'https://x/b.zip',
      filename: 'b.zip',
      status: 'completed',
      total_size: 500,
      downloaded_bytes: 500,
      error_message: null,
      hoster: 'direct',
      retry_after: null,
    },
  ],
}

const noop = () => {}

test('renders package name, status, and aggregate progress', () => {
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} />)

  expect(screen.getByText('My package')).toBeInTheDocument()
  expect(screen.getByText('running')).toBeInTheDocument()
  // aggregate: (400 + 500) / (1000 + 500) = 60%
  expect(screen.getByText('60%')).toBeInTheDocument()
})

test('prefers live progress over the last persisted byte count', () => {
  // The DB checkpoints every few seconds; the WS feed is ~500ms. Rendering the
  // stale DB value while a fresher one is in hand would make the bar stutter
  // backwards on every refetch.
  render(
    <PackageRow
      package={pkg}
      progressByItemId={{ i1: 1000 }}
      onPause={noop}
      onResume={noop}
      onCancel={noop}
    />,
  )

  expect(screen.getByText('100%')).toBeInTheDocument()
})

test('shows 0% instead of NaN before any size is known', () => {
  const unsized: Package = {
    ...pkg,
    items: [{ ...pkg.items[0], total_size: null, downloaded_bytes: 0 }],
  }
  render(<PackageRow package={unsized} onPause={noop} onResume={noop} onCancel={noop} />)

  expect(screen.getByText('0%')).toBeInTheDocument()
})

test('offers pause while running and resume while paused', () => {
  const onPause = vi.fn()
  const { rerender } = render(
    <PackageRow package={pkg} onPause={onPause} onResume={noop} onCancel={noop} />,
  )

  fireEvent.click(screen.getByRole('button', { name: 'Pausar' }))
  expect(onPause).toHaveBeenCalledWith('pkg-1')
  expect(screen.queryByRole('button', { name: 'Reanudar' })).not.toBeInTheDocument()

  const onResume = vi.fn()
  rerender(
    <PackageRow
      package={{ ...pkg, status: 'paused' }}
      onPause={noop}
      onResume={onResume}
      onCancel={noop}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: 'Reanudar' }))
  expect(onResume).toHaveBeenCalledWith('pkg-1')
  expect(screen.queryByRole('button', { name: 'Pausar' })).not.toBeInTheDocument()
})

test('hides cancel once the package is finished', () => {
  // Cancelling a completed package has no effect on the backend - offering it
  // just invites a click that appears to do nothing.
  render(
    <PackageRow
      package={{ ...pkg, status: 'completed' }}
      onPause={noop}
      onResume={noop}
      onCancel={noop}
    />,
  )

  expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument()
})

test('shows when a waiting item resumes instead of calling it an error', () => {
  const waiting: Package = {
    ...pkg,
    status: 'queued',
    items: [
      {
        ...pkg.items[0],
        status: 'queued',
        retry_after: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
      },
    ],
  }

  render(<PackageRow package={waiting} onPause={noop} onResume={noop} onCancel={noop} />)

  // "Esto está agendado" y "esto se rompió" se confunden fácil, y la confusión
  // hace que la gente cancele descargas que iban bien.
  expect(screen.getByText(/esperando hasta/i)).toBeInTheDocument()
})

test('does not claim a wait when there is none', () => {
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} />)
  expect(screen.queryByText(/esperando hasta/i)).not.toBeInTheDocument()
})
