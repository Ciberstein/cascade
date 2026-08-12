import { useCallback, useEffect, useRef, useState } from 'react'
import { getCrawlJob, promoteResults } from '../api/crawl'
import Masthead from '../components/Masthead'
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
  // Calidad elegida por resultado; lo que no esté acá usa la mejor.
  const [quality, setQuality] = useState<Record<string, string>>({})
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
      await promoteResults(jobId, name.trim() || 'Paquete sin nombre', [...selected], quality)
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo crear el paquete')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      {/* Fuera del form a propósito: un <button> sin type dentro de un form lo
          envía, y "Volver" encolaría el paquete. */}
      <Masthead>
        <button onClick={onBack}>Volver</button>
      </Masthead>

      <form onSubmit={handleSubmit}>
        <ol className="stages">
          <li>pegar</li>
          <li className="stages__arrow" aria-hidden="true">
            →
          </li>
          <li className="stages__step--now" aria-current="step">
            elegir
          </li>
          <li className="stages__arrow" aria-hidden="true">
            →
          </li>
          <li>recibir</li>
        </ol>

        <h1 className="grabber__title">Elegí qué se descarga</h1>
        <p className="grabber__lede">
          Esto es lo que hay detrás de los enlaces que pegaste. Destildá lo que no quieras y, en los
          videos, elegí con qué calidad bajarlos.
        </p>

        {error && (
          <p className="notice grabber__error" role="alert">
            {error}
          </p>
        )}

        {!finished && <p className="grabber__pending">Buscando qué hay detrás de los enlaces…</p>}

        {/* Un job que murió dejaba la pantalla en silencio: sin la lista y sin
            el "Buscando…", no quedaba nada que explicara la lista vacía. */}
        {job?.status === 'error' && (
          <p className="notice grabber__error" role="alert">
            {job.error_message ?? 'La búsqueda no terminó. Probá de nuevo con esos enlaces.'}
          </p>
        )}

        {job && job.results.length > 0 && (
          <ul className="grabber__list">
            {job.results.map((result) => {
              const on = selected.has(result.id)
              return (
                <li
                  className={`result${on ? ' result--on' : ''}${result.status === 'ok' ? '' : ' result--dead'}`}
                  key={result.id}
                >
                  <input
                    type="checkbox"
                    className="result__check"
                    id={`r-${result.id}`}
                    aria-label={result.filename}
                    checked={on}
                    disabled={result.status !== 'ok'}
                    onChange={() => toggle(result.id)}
                  />

                  <div className="result__body">
                    <div className="result__head">
                      <label className="result__name" htmlFor={`r-${result.id}`} title={result.url}>
                        {result.filename}
                      </label>
                      <StatusBadge status={result.status} kind="search" />
                    </div>

                    <div className="result__meta">
                      <span>{result.hoster}</span>
                      {result.variants.length > 0 ? (
                        <select
                          className="result__quality"
                          aria-label={`Calidad de ${result.filename}`}
                          value={quality[result.id] ?? result.variants[0].id}
                          onChange={(e) =>
                            setQuality((prev) => ({
                              ...prev,
                              [result.id]: e.target.value,
                            }))
                          }
                        >
                          {result.variants.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.label}
                              {v.size ? ` · ${formatBytes(v.size)}` : ''}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span>{formatBytes(result.size)}</span>
                      )}
                      {result.error_message && (
                        <span className="result__why">{result.error_message}</span>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}

        {finished && job?.results.length === 0 && (
          <p className="grabber__pending">No se encontró ningún archivo detrás de esos enlaces.</p>
        )}

        <div className="grabber__foot">
          <div className="grabber__field">
            <label className="eyebrow" htmlFor="pkg-name">
              Nombre del paquete
            </label>
            <input
              id="pkg-name"
              placeholder="Paquete sin nombre"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="grabber__confirm">
            <span className="grabber__tally">
              {selected.size} de {job?.results.length ?? 0}
            </span>
            <button type="submit" className="primary" disabled={selected.size === 0 || submitting}>
              Agregar a la cola
            </button>
          </div>
        </div>
      </form>
    </>
  )
}
