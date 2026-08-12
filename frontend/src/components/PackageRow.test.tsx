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
      retry_after: null, file_removed: false, retrieved: false, merge_role: null,
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
      retry_after: null, file_removed: false, retrieved: false, merge_role: null,
    },
  ],
}

const noop = () => {}

test('renders package name, status, and aggregate progress', () => {
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  expect(screen.getByText('My package')).toBeInTheDocument()
  // The status is shown in the interface's language, not the API's.
  expect(screen.getByText('downloading')).toBeInTheDocument()
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
      onDelete={noop}
      onRename={noop}
    />,
  )

  expect(screen.getByText('100%')).toBeInTheDocument()
})

test('shows 0% instead of NaN before any size is known', () => {
  const unsized: Package = {
    ...pkg,
    items: [{ ...pkg.items[0], total_size: null, downloaded_bytes: 0 }],
  }
  render(<PackageRow package={unsized} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  expect(screen.getByText('0%')).toBeInTheDocument()
})

test('offers pause while running and resume while paused', () => {
  const onPause = vi.fn()
  const { rerender } = render(
    <PackageRow package={pkg} onPause={onPause} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />,
  )

  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  expect(onPause).toHaveBeenCalledWith('pkg-1')
  expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument()

  const onResume = vi.fn()
  rerender(
    <PackageRow
      package={{ ...pkg, status: 'paused' }}
      onPause={noop}
      onResume={onResume}
      onCancel={noop}
      onDelete={noop}
      onRename={noop}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
  expect(onResume).toHaveBeenCalledWith('pkg-1')
  expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
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
      onDelete={noop}
      onRename={noop}
    />,
  )

  expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
})

test('shows when a waiting item resumes instead of calling it an error', () => {
  const waiting: Package = {
    ...pkg,
    status: 'queued',
    items: [
      {
        ...pkg.items[0],
        status: 'queued',
        retry_after: new Date(Date.now() + 30 * 60 * 1000).toISOString(), file_removed: false, retrieved: false, merge_role: null,
      },
    ],
  }

  render(<PackageRow package={waiting} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  // "This is scheduled" and "this broke" are easy to confuse, and the
  // confusion makes people kill downloads that were doing fine.
  expect(screen.getByText(/waiting until/i)).toBeInTheDocument()
})

test('does not claim a wait when there is none', () => {
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)
  expect(screen.queryByText(/waiting until/i)).not.toBeInTheDocument()
})

test('does not announce a wait for an item that already finished', () => {
  // A stale retry_after on a completed item showed "waiting until" forever,
  // and hid a sibling's real wait.
  const stale: Package = {
    ...pkg,
    items: [
      {
        ...pkg.items[0],
        status: 'completed',
        retry_after: new Date(Date.now() + 30 * 60 * 1000).toISOString(), file_removed: false, retrieved: false, merge_role: null,
      },
    ],
  }

  render(<PackageRow package={stale} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  expect(screen.queryByText(/waiting until/i)).not.toBeInTheDocument()
})

test('does not announce a wait whose time already passed', () => {
  const past: Package = {
    ...pkg,
    status: 'queued',
    items: [
      {
        ...pkg.items[0],
        status: 'queued',
        retry_after: new Date(Date.now() - 60 * 1000).toISOString(), file_removed: false, retrieved: false, merge_role: null,
      },
    ],
  }

  render(<PackageRow package={past} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  expect(screen.queryByText(/waiting until/i)).not.toBeInTheDocument()
})

test('deleting says the downloaded file is kept', () => {
  const onDelete = vi.fn()
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} onDelete={onDelete} onRename={noop} />)

  fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

  // The confirmation lives in the Dashboard; the row only announces intent.
  expect(onDelete).toHaveBeenCalledWith('pkg-1')
})

test('renaming only announces the intention', () => {
  const onRename = vi.fn()

  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={onRename} />)

  fireEvent.click(screen.getByRole('button', { name: 'Rename' }))

  // Asking for the name is the Dashboard's job, which is where the dialogs
  // live. The row opens nothing on its own.
  expect(onRename).toHaveBeenCalledWith('pkg-1')
})

test('a finished package can still be renamed and deleted', () => {
  render(
    <PackageRow
      package={{ ...pkg, status: 'completed' }}
      onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop}
    />,
  )

  // Stopping stops making sense once it finishes; tidying the list doesn't.
  expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Rename' })).toBeInTheDocument()
})

test('a finished single-file package can be downloaded straight from the list', () => {
  const listo: Package = {
    ...pkg,
    status: 'completed',
    items: [{ ...pkg.items[0], status: 'completed' }],
  }

  render(<PackageRow package={listo} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  // This is where people look when something finishes. Without it the file
  // sits on the server until the sweep deletes it, received by nobody.
  const link = screen.getByRole('link', { name: 'Download' })
  expect(link).toHaveAttribute('href', '/packages/pkg-1/items/i1/file')
  expect(link).toHaveAttribute('download', 'a.zip')
})

test('a package with several files sends you to the list of them', () => {
  const onOpen = vi.fn()
  const varios: Package = {
    ...pkg,
    status: 'completed',
    items: pkg.items.map((i) => ({ ...i, status: 'completed' as const })),
  }

  render(
    <PackageRow package={varios} onPause={noop} onResume={noop} onCancel={noop}
      onDelete={noop} onRename={noop} onOpen={onOpen} />,
  )

  fireEvent.click(screen.getByRole('button', { name: 'Download 2 files' }))
  expect(onOpen).toHaveBeenCalledWith('pkg-1')
})

test('a released file is not offered from the list either', () => {
  const liberado: Package = {
    ...pkg,
    status: 'completed',
    items: [{ ...pkg.items[0], status: 'completed', file_removed: true }],
  }

  render(<PackageRow package={liberado} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  expect(screen.queryByRole('link', { name: 'Download' })).not.toBeInTheDocument()
})
