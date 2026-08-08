import { useMemo, useState } from 'react'
import './AddLinksModal.css'

interface Props {
  onSubmit: (name: string, urls: string[]) => void
  onClose: () => void
  /** Set while the create request is in flight. */
  submitting?: boolean
  error?: string | null
}

export default function AddLinksModal({ onSubmit, onClose, submitting = false, error }: Props) {
  const [name, setName] = useState('')
  const [raw, setRaw] = useState('')

  const { urls, duplicates } = useMemo(() => parseLinks(raw), [raw])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    // The backend rejects an empty name (min_length=1), so give it one rather
    // than surfacing a 422 the user can't act on.
    onSubmit(name.trim() || 'Paquete sin nombre', urls)
  }

  return (
    <div
      className="modal__backdrop"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <form className="modal" role="dialog" aria-modal="true" aria-label="Agregar enlaces" onSubmit={handleSubmit}>
        <h2 className="modal__title">Agregar enlaces</h2>

        <div className="modal__field">
          <label htmlFor="package-name">Nombre del paquete</label>
          <input
            id="package-name"
            autoFocus
            placeholder="Paquete sin nombre"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="modal__field">
          <label htmlFor="links">Enlaces</label>
          <textarea
            id="links"
            rows={8}
            placeholder="Una URL por línea"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
          />
        </div>

        <p className="modal__hint">
          {urls.length} enlace{urls.length === 1 ? '' : 's'}
          {duplicates > 0 &&
            ` · ${duplicates} enlace${duplicates === 1 ? '' : 's'} duplicado${duplicates === 1 ? '' : 's'} omitido${duplicates === 1 ? '' : 's'}`}
        </p>

        {error && (
          <p className="modal__error" role="alert">
            {error}
          </p>
        )}

        <div className="modal__actions">
          <button type="button" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" className="modal__primary" disabled={urls.length === 0 || submitting}>
            Agregar
          </button>
        </div>
      </form>
    </div>
  )
}

/**
 * Splits the textarea into unique, non-empty URLs.
 *
 * De-duplicating here (rather than letting the backend queue the same file
 * twice) covers the usual cause: pasting a list that already overlaps one the
 * user pasted a moment ago. The count is reported back so the omission is
 * visible instead of silent.
 */
function parseLinks(raw: string): { urls: string[]; duplicates: number } {
  const lines = raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)

  const urls = [...new Set(lines)]
  return { urls, duplicates: lines.length - urls.length }
}
