import { expect, test } from 'vitest'
import { formatBytes } from './format'

test('formats byte counts at a human scale', () => {
  expect(formatBytes(0)).toBe('0 B')
  expect(formatBytes(512)).toBe('512 B')
  expect(formatBytes(1024)).toBe('1.0 KB')
  expect(formatBytes(1536)).toBe('1.5 KB')
  expect(formatBytes(1024 * 1024 * 3.5)).toBe('3.5 MB')
  expect(formatBytes(1024 ** 3 * 2)).toBe('2.0 GB')
})

test('renders an unknown size as a dash rather than 0 B', () => {
  // total_size is null until the probe reads Content-Length; "0 B" there would
  // read as an empty file instead of "not measured yet".
  expect(formatBytes(null)).toBe('—')
})
