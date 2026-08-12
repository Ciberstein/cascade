import { useMemo, useState } from 'react'
import './LinkIntake.css'

interface Props {
  onSubmit: (urls: string[]) => void
  /** Set while the analysis is being created. */
  submitting?: boolean
  error?: string | null
}

export default function LinkIntake({ onSubmit, submitting = false, error }: Props) {
  const [raw, setRaw] = useState('')

  const { urls, duplicates } = useMemo(() => parseLinks(raw), [raw])

  function submit() {
    // The package name isn't asked for here: it is chosen at confirmation time,
    // once the user has seen which files turned up.
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
          Links
        </label>

        <textarea
          id="links"
          className="intake__input"
          rows={4}
          placeholder="One URL per line"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={(e) => {
            // A bare Enter just breaks the line, which is right for a list of
            // URLs; the shortcut is for whoever pastes and wants to move on.
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
              {urls.length} link{urls.length === 1 ? '' : 's'}
              {duplicates > 0 &&
                ` · ${duplicates} duplicate link${duplicates === 1 ? '' : 's'} skipped`}
            </p>
          ) : (
            <p className="intake__how">
              First we look at what is behind each link. Then you pick the quality and the file
              lands in your downloads folder.
            </p>
          )}

          <button type="submit" className="primary" disabled={urls.length === 0 || submitting}>
            Check links
          </button>
        </div>
      </form>
    </section>
  )
}

/**
 * Splits the text into unique, non-empty URLs.
 *
 * De-duplicating here (rather than letting the backend queue the same file
 * twice) covers the usual cause: pasting a list that already overlaps one
 * pasted a moment ago. The count is reported back so the omission is visible
 * instead of silent.
 */
function parseLinks(raw: string): { urls: string[]; duplicates: number } {
  const lines = raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)

  const urls = [...new Set(lines)]
  return { urls, duplicates: lines.length - urls.length }
}
