import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import LinkGrabber from './LinkGrabber'
import * as crawlApi from '../api/crawl'
import type { CrawlJob } from '../types'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const doneJob: CrawlJob = {
  id: 'j1',
  raw_input: 'http://x/dir/',
  status: 'done',
  error_message: null,
  results: [
    { id: 'r1', url: 'http://x/a.zip', filename: 'a.zip', size: 1024, hoster: 'direct', status: 'ok', error_message: null, variants: [] },
    { id: 'r2', url: 'http://x/b.zip', filename: 'b.zip', size: null, hoster: 'direct', status: 'dead', error_message: 'no existe', variants: [] },
  ],
}

test('renders the discovered files once the job is done', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)

  expect(await screen.findByText('a.zip')).toBeInTheDocument()
  expect(screen.getByText('b.zip')).toBeInTheDocument()
  expect(screen.getByText('1.0 KB')).toBeInTheDocument()
})

test('dead links are shown but not selected', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  await screen.findByText('a.zip')

  // Verlos importa: dicen qué se perdió de la lista pegada. Tildarlos solo
  // encolaría un fallo garantizado.
  expect(screen.getByLabelText('a.zip')).toBeChecked()
  expect(screen.getByLabelText('b.zip')).not.toBeChecked()
  expect(screen.getByLabelText('b.zip')).toBeDisabled()
})

test('promotes only the checked results', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)
  const promote = vi.spyOn(crawlApi, 'promoteResults').mockResolvedValue({
    id: 'p1', name: 'Mi paquete', status: 'queued', target_dir: '/x', items: [],
  })
  const onDone = vi.fn()

  render(<LinkGrabber jobId="j1" onDone={onDone} onBack={vi.fn()} />)
  await screen.findByText('a.zip')

  fireEvent.change(screen.getByLabelText('Nombre del paquete'), { target: { value: 'Mi paquete' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar a la cola' }))

  await waitFor(() => expect(promote).toHaveBeenCalledWith('j1', 'Mi paquete', ['r1'], {}))
  await waitFor(() => expect(onDone).toHaveBeenCalled())
})

test('keeps polling while the job is still running', async () => {
  vi.useFakeTimers()
  const get = vi
    .spyOn(crawlApi, 'getCrawlJob')
    .mockResolvedValueOnce({ ...doneJob, status: 'running', results: [] })
    .mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)

  await vi.waitFor(() => expect(screen.getByText(/Buscando/)).toBeInTheDocument())
  await vi.advanceTimersByTimeAsync(2000)

  await vi.waitFor(() => expect(screen.getByText('a.zip')).toBeInTheDocument())
  expect(get.mock.calls.length).toBeGreaterThan(1)
})

test('stops polling once the job is done', async () => {
  vi.useFakeTimers()
  const get = vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  await vi.waitFor(() => expect(screen.getByText('a.zip')).toBeInTheDocument())

  const callsWhenDone = get.mock.calls.length
  await vi.advanceTimersByTimeAsync(10000)

  // Un job terminado no cambia más; seguir sondeándolo es tráfico puro.
  expect(get.mock.calls.length).toBe(callsWhenDone)
})

test('submit is disabled when nothing is selected', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue({
    ...doneJob,
    results: [doneJob.results[1]], // solo el muerto
  })

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  await screen.findByText('b.zip')

  expect(screen.getByRole('button', { name: 'Agregar a la cola' })).toBeDisabled()
})

test('a video offers its qualities and sends the chosen one', async () => {
  const conCalidades: CrawlJob = {
    ...doneJob,
    results: [
      {
        id: 'r1', url: 'https://sitio/v', filename: 'video.mp4', size: null,
        hoster: 'ytdlp', status: 'ok', error_message: null,
        variants: [
          { id: '299', label: '1080p', height: 1080, size: 288000000, needs_merge: true },
          { id: '18', label: '360p', height: 360, size: 29000000, needs_merge: false },
        ],
      },
    ],
  }
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(conCalidades)
  const promote = vi.spyOn(crawlApi, 'promoteResults').mockResolvedValue({
    id: 'p1', name: 'x', status: 'queued', target_dir: '/x', items: [],
  })

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  const selector = await screen.findByLabelText('Calidad de video.mp4')

  // La mejor viene preseleccionada: quien no elige espera la mejor.
  expect(selector).toHaveValue('299')

  fireEvent.change(selector, { target: { value: '18' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar a la cola' }))

  await waitFor(() =>
    expect(promote).toHaveBeenCalledWith('j1', 'Paquete sin nombre', ['r1'], { r1: '18' }),
  )
})

test('something that is not a video shows its size instead of a picker', async () => {
  vi.spyOn(crawlApi, 'getCrawlJob').mockResolvedValue(doneJob)

  render(<LinkGrabber jobId="j1" onDone={vi.fn()} onBack={vi.fn()} />)
  await screen.findByText('a.zip')

  expect(screen.queryByLabelText(/Calidad de/)).not.toBeInTheDocument()
  expect(screen.getByText('1.0 KB')).toBeInTheDocument()
})
