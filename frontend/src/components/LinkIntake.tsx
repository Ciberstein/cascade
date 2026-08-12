import { useMemo, useState } from 'react'
import './LinkIntake.css'

interface Props {
  onSubmit: (urls: string[]) => void
  /** Mientras se crea el análisis. */
  submitting?: boolean
  error?: string | null
}

export default function LinkIntake({ onSubmit, submitting = false, error }: Props) {
  const [raw, setRaw] = useState('')

  const { urls, duplicates } = useMemo(() => parseLinks(raw), [raw])

  function submit() {
    // El nombre del paquete no se pide acá: se elige al confirmar, cuando el
    // usuario ya vio qué archivos aparecieron.
    if (urls.length > 0 && !submitting) onSubmit(urls)
  }

  return (
    <section className="intake">
      <div className="intake__rail" aria-hidden="true" />

      <form
        className="intake__body"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <label className="eyebrow" htmlFor="links">
          Enlaces
        </label>

        <textarea
          id="links"
          className="intake__input"
          rows={4}
          placeholder="Una URL por línea"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={(e) => {
            // Enter solo hace un salto de línea, que es lo correcto en una
            // lista de URLs; el atajo cubre a quien pega y quiere seguir.
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              submit()
            }
          }}
        />

        {error && (
          <p className="notice" role="alert">
            {error}
          </p>
        )}

        <div className="intake__foot">
          {urls.length > 0 ? (
            <p className="intake__count">
              {urls.length} enlace{urls.length === 1 ? '' : 's'}
              {duplicates > 0 &&
                ` · ${duplicates} enlace${duplicates === 1 ? '' : 's'} duplicado${duplicates === 1 ? '' : 's'} omitido${duplicates === 1 ? '' : 's'}`}
            </p>
          ) : (
            <p className="intake__how">
              Primero se ve qué hay detrás de cada enlace. Después elegís calidad y el archivo baja a
              tu carpeta de descargas.
            </p>
          )}

          <button type="submit" className="primary" disabled={urls.length === 0 || submitting}>
            Analizar
          </button>
        </div>
      </form>
    </section>
  )
}

/**
 * Parte el texto en URLs únicas y no vacías.
 *
 * Deduplicar acá (en vez de dejar que el backend encole el mismo archivo dos
 * veces) cubre el caso habitual: pegar una lista que ya se solapa con la que
 * se pegó hace un rato. El descarte se informa para que no sea silencioso.
 */
function parseLinks(raw: string): { urls: string[]; duplicates: number } {
  const lines = raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)

  const urls = [...new Set(lines)]
  return { urls, duplicates: lines.length - urls.length }
}
