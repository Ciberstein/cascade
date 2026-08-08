import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import AddLinksModal from './AddLinksModal'

test('parses newline-separated URLs and calls onSubmit', () => {
  const onSubmit = vi.fn()
  render(<AddLinksModal onSubmit={onSubmit} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/b.zip\n\nhttps://x/c.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip', 'https://x/c.zip'])
})

test('disables submit when no urls entered', () => {
  render(<AddLinksModal onSubmit={vi.fn()} onClose={() => {}} />)
  expect(screen.getByRole('button', { name: 'Analizar' })).toBeDisabled()
})

test('disables submit when the textarea holds only whitespace', () => {
  render(<AddLinksModal onSubmit={vi.fn()} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: '  \n\n   \n' } })

  // POST /packages requires min_length=1 urls; sending an empty list would be
  // a 422 the user can't act on.
  expect(screen.getByRole('button', { name: 'Analizar' })).toBeDisabled()
})

test('drops duplicate URLs before submitting', () => {
  const onSubmit = vi.fn()
  render(<AddLinksModal onSubmit={onSubmit} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/a.zip\nhttps://x/b.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip'])
  expect(screen.getByText(/1 enlace duplicado/)).toBeInTheDocument()
})

test('closes on cancel and on Escape', () => {
  const onClose = vi.fn()
  render(<AddLinksModal onSubmit={vi.fn()} onClose={onClose} />)

  fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
  expect(onClose).toHaveBeenCalledTimes(1)

  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(2)
})
