import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import AddLinksModal from './AddLinksModal'

test('parses newline-separated URLs and calls onSubmit', () => {
  const onSubmit = vi.fn()
  render(<AddLinksModal onSubmit={onSubmit} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/b.zip\n\nhttps://x/c.zip' },
  })
  fireEvent.change(screen.getByLabelText('Nombre del paquete'), { target: { value: 'Mi paquete' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar' }))

  expect(onSubmit).toHaveBeenCalledWith('Mi paquete', [
    'https://x/a.zip',
    'https://x/b.zip',
    'https://x/c.zip',
  ])
})

test('disables submit when no urls entered', () => {
  render(<AddLinksModal onSubmit={vi.fn()} onClose={() => {}} />)
  expect(screen.getByRole('button', { name: 'Agregar' })).toBeDisabled()
})

test('disables submit when the textarea holds only whitespace', () => {
  render(<AddLinksModal onSubmit={vi.fn()} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: '  \n\n   \n' } })

  // POST /packages requires min_length=1 urls; sending an empty list would be
  // a 422 the user can't act on.
  expect(screen.getByRole('button', { name: 'Agregar' })).toBeDisabled()
})

test('drops duplicate URLs before submitting', () => {
  const onSubmit = vi.fn()
  render(<AddLinksModal onSubmit={onSubmit} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/a.zip\nhttps://x/b.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar' }))

  // Pasting a list twice is the common way this happens; the spec asks that
  // duplicates be surfaced rather than silently queued twice.
  expect(onSubmit).toHaveBeenCalledWith(expect.any(String), ['https://x/a.zip', 'https://x/b.zip'])
  expect(screen.getByText(/1 enlace duplicado/)).toBeInTheDocument()
})

test('falls back to a default package name', () => {
  const onSubmit = vi.fn()
  render(<AddLinksModal onSubmit={onSubmit} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: 'https://x/a.zip' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar' }))

  // The backend rejects an empty name (min_length=1).
  expect(onSubmit).toHaveBeenCalledWith('Paquete sin nombre', ['https://x/a.zip'])
})

test('closes on cancel and on Escape', () => {
  const onClose = vi.fn()
  render(<AddLinksModal onSubmit={vi.fn()} onClose={onClose} />)

  fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
  expect(onClose).toHaveBeenCalledTimes(1)

  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(2)
})
