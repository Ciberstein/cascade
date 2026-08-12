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
  // Quality chosen per result; anything not here uses the best available.
  const [quality, setQuality] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const finished = job?.status === 'done' || job?.status === 'error'

  const refresh = useCallback(async () => {
    try {
      const fetched = await getCrawlJob(jobId)
      setJob(fetched)
      // Dead links stay visible but out of the selection: ticking one only
      // queues a guaranteed failure.
      //
      // An explicit flag rather than "prev.size > 0": while the job runs the
      // poll stays active, so treating "empty" as a synonym for "not yet
      // initialised" makes unticking the last box re-tick them all a second
      // later.
      if (!selectionInitialized.current && fetched.results.length > 0) {
        selectionInitialized.current = true
        setSelected(new Set(fetched.results.filter((r) => r.status === 'ok').map((r) => r.id)))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the results')
    }
  }, [jobId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    // A finished job never changes; polling it further is pure traffic.
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
      await promoteResults(jobId, name.trim() || 'Untitled package', [...selected], quality)
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the package')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      {/* Outside the form on purpose: a <button> with no type inside a form
          submits it, and "Back" would queue the package. */}
      <Masthead>
        <button onClick={onBack}>Back</button>
      </Masthead>

      <form onSubmit={handleSubmit}>
        <ol className="stages">
          <li>paste</li>
          <li className="stages__arrow" aria-hidden="true">
            →
          </li>
          <li className="stages__step--now" aria-current="step">
            choose
          </li>
          <li className="stages__arrow" aria-hidden="true">
            →
          </li>
          <li>receive</li>
        </ol>

        <h1 className="grabber__title">Choose what to download</h1>
        <p className="grabber__lede">
          This is what sits behind the links you pasted. Untick anything you don't want and, for
          videos, pick the quality to fetch.
        </p>

        {error && (
          <p className="notice grabber__error" role="alert">
            {error}
          </p>
        )}

        {!finished && <p className="grabber__pending">Looking at what is behind those links…</p>}

        {/* A job that died left the screen silent: with no list and no
            "Looking at…", nothing explained why it was empty. */}
        {job?.status === 'error' && (
          <p className="notice grabber__error" role="alert">
            {job.error_message ?? 'The search did not finish. Try those links again.'}
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
                          aria-label={`Quality for ${result.filename}`}
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
          <p className="grabber__pending">No files were found behind those links.</p>
        )}

        <div className="grabber__foot">
          <div className="grabber__field">
            <label className="eyebrow" htmlFor="pkg-name">
              Package name
            </label>
            <input
              id="pkg-name"
              placeholder="Untitled package"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="grabber__confirm">
            <span className="grabber__tally">
              {selected.size} de {job?.results.length ?? 0}
            </span>
            <button type="submit" className="primary" disabled={selected.size === 0 || submitting}>
              Add to queue
            </button>
          </div>
        </div>
      </form>
    </>
  )
}
