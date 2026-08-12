import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import LinkIntake from './LinkIntake'

test('parses newline-separated URLs and calls onSubmit', () => {
  const onSubmit = vi.fn()
  render(<LinkIntake onSubmit={onSubmit} />)

  fireEvent.change(screen.getByLabelText('Links'), {
    target: { value: 'https://x/a.zip\nhttps://x/b.zip\n\nhttps://x/c.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Check links' }))

  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip', 'https://x/c.zip'])
})

test('disables submit when no urls entered', () => {
  render(<LinkIntake onSubmit={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Check links' })).toBeDisabled()
})

test('disables submit when the textarea holds only whitespace', () => {
  render(<LinkIntake onSubmit={vi.fn()} />)

  fireEvent.change(screen.getByLabelText('Links'), { target: { value: '  \n\n   \n' } })

  // POST /packages requires min_length=1 urls; sending an empty list would be
  // a 422 the user can't act on.
  expect(screen.getByRole('button', { name: 'Check links' })).toBeDisabled()
})

test('drops duplicate URLs before submitting', () => {
  const onSubmit = vi.fn()
  render(<LinkIntake onSubmit={onSubmit} />)

  fireEvent.change(screen.getByLabelText('Links'), {
    target: { value: 'https://x/a.zip\nhttps://x/a.zip\nhttps://x/b.zip' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Check links' }))

  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip', 'https://x/b.zip'])
  expect(screen.getByText(/1 duplicate link/)).toBeInTheDocument()
})

test('submits with the keyboard shortcut', () => {
  const onSubmit = vi.fn()
  render(<LinkIntake onSubmit={onSubmit} />)

  const field = screen.getByLabelText('Links')
  fireEvent.change(field, { target: { value: 'https://x/a.zip' } })
  // A bare Enter must keep breaking the line: the field is a list of URLs,
  // not a search box.
  fireEvent.keyDown(field, { key: 'Enter' })
  expect(onSubmit).not.toHaveBeenCalled()

  fireEvent.keyDown(field, { key: 'Enter', ctrlKey: true })
  expect(onSubmit).toHaveBeenCalledWith(['https://x/a.zip'])
})

test('says nothing about counts until something is pasted', () => {
  render(<LinkIntake onSubmit={vi.fn()} />)

  // "0 links" over an empty field is noise: what is needed there is knowing
  // what happens after you paste.
  expect(screen.queryByText(/0 links/)).not.toBeInTheDocument()
  expect(screen.getByText(/pick the quality/)).toBeInTheDocument()
})
