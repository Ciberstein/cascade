import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import PackageDetail from './PackageDetail'
import type { Package } from '../types'

const pkg: Package = {
  id: 'p1',
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
      downloaded_bytes: 250,
      error_message: null,
      hoster: 'direct',
      retry_after: null, file_removed: false, retrieved: false, merge_role: null,
    },
    {
      id: 'i2',
      url: 'https://x/b.zip',
      filename: 'b.zip',
      status: 'error',
      total_size: null,
      downloaded_bytes: 0,
      error_message: 'timeout',
      hoster: 'direct',
      retry_after: null, file_removed: false, retrieved: false, merge_role: null,
    },
  ],
}

test('renders each item with its own progress and errors', () => {
  render(<PackageDetail package={pkg} onBack={() => {}} />)

  expect(screen.getByText('a.zip')).toBeInTheDocument()
  expect(screen.getByText('25%')).toBeInTheDocument()
  expect(screen.getByText('b.zip')).toBeInTheDocument()
  expect(screen.getByText('timeout')).toBeInTheDocument()
})

test('shows the target directory so the user knows where files landed', () => {
  render(<PackageDetail package={pkg} onBack={() => {}} />)

  expect(screen.getByText('/downloads/my-package')).toBeInTheDocument()
})

test('applies live progress per item', () => {
  render(<PackageDetail package={pkg} progressByItemId={{ i1: 750 }} onBack={() => {}} />)

  expect(screen.getByText('75%')).toBeInTheDocument()
})

test('does not report a failed item as 0% of nothing', () => {
  // total_size stays null when the probe itself failed; the row must lead with
  // the error, not an empty bar that looks like it is still working.
  render(<PackageDetail package={pkg} onBack={() => {}} />)

  const errored = screen.getByText('b.zip').closest('li')
  expect(errored).not.toBeNull()
  expect(errored).toHaveTextContent('timeout')
})

test('a finished file offers a link the browser will download', () => {
  render(<PackageDetail package={{ ...pkg, items: [{ ...pkg.items[0], status: 'completed' }] }} onBack={() => {}} />)

  const link = screen.getByRole('link', { name: /Download to my computer/ })
  // href + download: this way the browser fetches it and it lands in its
  // downloads folder. Cascade downloads to the server; this link is the
  // bridge to the user's machine.
  expect(link).toHaveAttribute('href', '/packages/p1/items/i1/file')
  expect(link).toHaveAttribute('download', 'a.zip')
})

test('an unfinished file offers nothing to download yet', () => {
  render(<PackageDetail package={pkg} onBack={() => {}} />)

  // The file exists half-written; offering it would hand over something
  // corrupt.
  expect(screen.queryByRole('link', { name: /Download/ })).not.toBeInTheDocument()
})

test('a released file explains itself instead of offering a dead link', () => {
  render(
    <PackageDetail
      package={{ ...pkg, items: [{ ...pkg.items[0], status: 'completed', file_removed: true }] }}
      onBack={() => {}}
    />,
  )

  // The server is a place to pass through: once retrieved, it frees its
  // copy. A link that answers 410 would be worse than saying so.
  expect(screen.getByText(/let its copy go/)).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Download/ })).not.toBeInTheDocument()
})

test('the audio track being merged is not listed as a file', () => {
  const uniendo = {
    ...pkg,
    items: [
      { ...pkg.items[0], filename: 'video.mp4', merge_role: 'video' },
      { ...pkg.items[0], id: 'i9', filename: 'video.mp4', merge_role: 'audio' },
    ],
  }

  render(<PackageDetail package={uniendo} onBack={() => {}} />)

  // It is a means to get the file, not a file the user asked for: listing it
  // would show two downloads where they asked for one.
  expect(screen.getAllByText('video.mp4')).toHaveLength(1)
})
