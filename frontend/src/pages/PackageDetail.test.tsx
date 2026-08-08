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
      retry_after: null,
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
      retry_after: null,
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
