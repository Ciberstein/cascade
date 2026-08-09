import { useCallback, useEffect, useRef, useState } from 'react'
import { getCrawlJob, promoteResults } from '../api/crawl'
import StatusBadge from '../components/StatusBadge'
import { formatBytes } from '../format'
import type { CrawlJob } from '../types'
import './LinkGrabber.css'

interface Props {
  jobId: string
  onDone: () => void
  onBack: () => void
}

const POLL_INTERVAL_MS = 1000

export default function LinkGrabber({ jobId, onDone, onBack }: Props) {
  const [job, setJob] = useState<CrawlJob | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const selectionInitialized = useRef(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const finished = job?.status === 'done' || job?.status === 'error'

  const refresh = useCallback(async () => {
    try {
      const fetched = await getCrawlJob(jobId)
      setJob(fetched)
      // Los muertos quedan visibles pero fuera de la selección: tildarlos solo
      // encola un fallo garantizado.
      //
      // La marca explícita, y no "prev.size > 0": mientras el job corre el
      // sondeo sigue activo, así que usar "está vacío" como sinónimo de "sin
      // inicializar" hace que destildar la última casilla vuelva a tildarlas
      // todas un segundo después.
      if (!selectionInitialized.current && fetched.results.length > 0) {
        selectionInitialized.current = true
        setSelected(new Set(fetched.results.filter((r) => r.status === 'ok').map((r) => r.id)))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo cargar el análisis')
    }
  }, [jobId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    // Un job terminado no cambia más; seguir sondeándolo es tráfico puro.
    if (finished) return
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [finished, refresh])

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await promoteResults(jobId, name.trim() || 'Paquete sin nombre', [...selected])
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo crear el paquete')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="grabber" onSubmit={handleSubmit}>
      <div className="grabber__header">
        <button type="button" onClick={onBack}>
          Volver
        </button>
        {job && <StatusBadge status={job.status} />}
      </div>

      <h1 className="grabber__title">Enlaces encontrados</h1>

      {error && (
        <p className="grabber__error" role="alert">
          {error}
        </p>
      )}

      {!finished && <p className="grabber__pending">Buscando qué hay detrás de los enlaces…</p>}

      {job && job.results.length > 0 && (
        <ul className="grabber__list">
          {job.results.map((result) => (
            <li className="grabber__row" key={result.id}>
              <input
                type="checkbox"
                id={`r-${result.id}`}
                aria-label={result.filename}
                checked={selected.has(result.id)}
                disabled={result.status !== 'ok'}
                onChange={() => toggle(result.id)}
              />
              <label className="grabber__name" htmlFor={`r-${result.id}`} title={result.url}>
                {result.filename}
              </label>
              <span className="grabber__size">{formatBytes(result.size)}</span>
              <span className="grabber__hoster">{result.hoster}</span>
              <StatusBadge status={result.status} />
              {result.error_message && <span className="grabber__why">{result.error_message}</span>}
            </li>
          ))}
        </ul>
      )}

      {finished && job?.results.length === 0 && (
        <p className="grabber__pending">No se encontró ningún archivo detrás de esos enlaces.</p>
      )}

      <div className="grabber__footer">
        <div className="grabber__field">
          <label htmlFor="pkg-name">Nombre del paquete</label>
          <input
            id="pkg-name"
            placeholder="Paquete sin nombre"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <button type="submit" className="grabber__primary" disabled={selected.size === 0 || submitting}>
          Agregar a la cola
        </button>
      </div>
    </form>
  )
}
