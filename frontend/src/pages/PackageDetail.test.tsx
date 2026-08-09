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
      retry_after: null, file_removed: false, merge_role: null,
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
      retry_after: null, file_removed: false, merge_role: null,
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

  const link = screen.getByRole('link', { name: /Descargar a mi equipo/ })
  // href + download: así lo baja el navegador y queda en su carpeta de
  // descargas. Cascade baja al servidor; este enlace es el puente hasta el
  // equipo del usuario.
  expect(link).toHaveAttribute('href', '/packages/p1/items/i1/file')
  expect(link).toHaveAttribute('download', 'a.zip')
})

test('an unfinished file offers nothing to download yet', () => {
  render(<PackageDetail package={pkg} onBack={() => {}} />)

  // El archivo existe a medio escribir; ofrecerlo daría algo corrupto.
  expect(screen.queryByRole('link', { name: /Descargar/ })).not.toBeInTheDocument()
})

test('a released file explains itself instead of offering a dead link', () => {
  render(
    <PackageDetail
      package={{ ...pkg, items: [{ ...pkg.items[0], status: 'completed', file_removed: true }] }}
      onBack={() => {}}
    />,
  )

  // El servidor es un lugar de paso: una vez retirado, libera su copia. Un
  // enlace que da 410 sería peor que decirlo.
  expect(screen.getByText(/el servidor liberó su copia/)).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Descargar/ })).not.toBeInTheDocument()
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

  // Es un medio para conseguir el archivo, no un archivo que el usuario pidió:
  // listarlo lo haría ver dos descargas donde pidió una.
  expect(screen.getAllByText('video.mp4')).toHaveLength(1)
})
