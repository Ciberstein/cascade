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
      onDelete={noop}
      onRename={noop}
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
      onDelete={noop}
      onRename={noop}
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
        retry_after: new Date(Date.now() + 30 * 60 * 1000).toISOString(), file_removed: false, retrieved: false, merge_role: null,
      },
    ],
  }

  render(<PackageRow package={waiting} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  // "Esto está agendado" y "esto se rompió" se confunden fácil, y la confusión
  // hace que la gente cancele descargas que iban bien.
  expect(screen.getByText(/esperando hasta/i)).toBeInTheDocument()
})

test('does not claim a wait when there is none', () => {
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)
  expect(screen.queryByText(/esperando hasta/i)).not.toBeInTheDocument()
})

test('does not announce a wait for an item that already finished', () => {
  // Un retry_after viejo sobre un item completado mostraba "esperando hasta"
  // para siempre, y tapaba la espera real de un item hermano.
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

  expect(screen.queryByText(/esperando hasta/i)).not.toBeInTheDocument()
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

  expect(screen.queryByText(/esperando hasta/i)).not.toBeInTheDocument()
})

test('deleting says the downloaded file is kept', () => {
  const onDelete = vi.fn()
  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} onDelete={onDelete} onRename={noop} />)

  fireEvent.click(screen.getByRole('button', { name: 'Eliminar' }))

  // La confirmación vive en el Dashboard; la fila solo avisa la intención.
  expect(onDelete).toHaveBeenCalledWith('pkg-1')
})

test('renaming asks for the new name and skips an empty one', () => {
  const onRename = vi.fn()
  const prompt = vi.spyOn(window, 'prompt')

  render(<PackageRow package={pkg} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={onRename} />)

  prompt.mockReturnValue('   ')
  fireEvent.click(screen.getByRole('button', { name: 'Renombrar' }))
  // La API rechaza un nombre vacío; no vale la pena viajar para que falle.
  expect(onRename).not.toHaveBeenCalled()

  prompt.mockReturnValue('  Backrooms  ')
  fireEvent.click(screen.getByRole('button', { name: 'Renombrar' }))
  expect(onRename).toHaveBeenCalledWith('pkg-1', 'Backrooms')

  prompt.mockRestore()
})

test('a finished package can still be renamed and deleted', () => {
  render(
    <PackageRow
      package={{ ...pkg, status: 'completed' }}
      onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop}
    />,
  )

  // Cancelar deja de tener sentido al terminar, pero limpiar la lista no.
  expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Eliminar' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Renombrar' })).toBeInTheDocument()
})

test('a finished single-file package can be downloaded straight from the list', () => {
  const listo: Package = {
    ...pkg,
    status: 'completed',
    items: [{ ...pkg.items[0], status: 'completed' }],
  }

  render(<PackageRow package={listo} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  // Es acá donde se mira cuando algo termina. Sin esto el archivo se queda en
  // el servidor hasta que el barrido lo borra sin que nadie lo reciba.
  const link = screen.getByRole('link', { name: 'Descargar' })
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

  fireEvent.click(screen.getByRole('button', { name: 'Descargar 2 archivos' }))
  expect(onOpen).toHaveBeenCalledWith('pkg-1')
})

test('a released file is not offered from the list either', () => {
  const liberado: Package = {
    ...pkg,
    status: 'completed',
    items: [{ ...pkg.items[0], status: 'completed', file_removed: true }],
  }

  render(<PackageRow package={liberado} onPause={noop} onResume={noop} onCancel={noop} onDelete={noop} onRename={noop} />)

  expect(screen.queryByRole('link', { name: 'Descargar' })).not.toBeInTheDocument()
})
