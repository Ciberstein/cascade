import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import LinkIntake from './LinkIntake'

test('parses newline-separated URLs and calls onSubmit', () => {
  const onSubmit = vi.fn()
  render(<LinkIntake onSubmit={onSubmit} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/b.zip\n\nhttps://x/c.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip', 'https://x/c.zip'])
})

test('disables submit when no urls entered', () => {
  render(<LinkIntake onSubmit={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Analizar' })).toBeDisabled()
})

test('disables submit when the textarea holds only whitespace', () => {
  render(<LinkIntake onSubmit={vi.fn()} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), { target: { value: '  \n\n   \n' } })

  // POST /packages requires min_length=1 urls; sending an empty list would be
  // a 422 the user can't act on.
  expect(screen.getByRole('button', { name: 'Analizar' })).toBeDisabled()
})

test('drops duplicate URLs before submitting', () => {
  const onSubmit = vi.fn()
  render(<LinkIntake onSubmit={onSubmit} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/a.zip\nhttps://x/b.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Analizar' }))

  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip'])
  expect(screen.getByText(/1 enlace duplicado/)).toBeInTheDocument()
})

test('submits with the keyboard shortcut', () => {
  const onSubmit = vi.fn()
  render(<LinkIntake onSubmit={onSubmit} />)

  const field = screen.getByLabelText('Enlaces')
  fireEvent.change(field, { target: { value: 'https://x/a.zip' } })
  // Enter suelto tiene que seguir haciendo un salto de línea: el campo es una
  // lista de URLs, no un buscador.
  fireEvent.keyDown(field, { key: 'Enter' })
  expect(onSubmit).not.toHaveBeenCalled()

  fireEvent.keyDown(field, { key: 'Enter', ctrlKey: true })
  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip'])
})

test('says nothing about counts until something is pasted', () => {
  render(<LinkIntake onSubmit={vi.fn()} />)

  // "0 enlaces" sobre un campo vacío es ruido: lo que hace falta ahí es saber
  // qué va a pasar después de pegar.
  expect(screen.queryByText(/0 enlaces/)).not.toBeInTheDocument()
  expect(screen.getByText(/elegís calidad/)).toBeInTheDocument()
})
