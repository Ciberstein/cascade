import { useEffect, useState } from 'react'
import { getSettings, updateSettings } from '../api/settings'
import Masthead from '../components/Masthead'
import type { AppSettings } from '../types'
import './Settings.css'

interface Props {
  onClose: () => void
}

/** Mirrors the Field(ge=…, le=…) bounds on UpdateSettingsRequest. */
const BOUNDS: Record<NumericKey, { min: number; max?: number }> = {
  max_concurrent_downloads: { min: 1, max: 20 },
  chunks_per_file: { min: 1, max: 16 },
  max_speed_kbps: { min: 0 },
  max_concurrent_crawls: { min: 1, max: 20 },
}

type NumericKey =
  'max_concurrent_downloads' | 'chunks_per_file' | 'max_speed_kbps' | 'max_concurrent_crawls'

export default function Settings({ onClose }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  // Number inputs are held as strings so a half-typed value ("" while
  // retyping) stays exactly what the user sees, instead of being coerced to 0
  // and silently sent to an API that rejects it.
  const [numeric, setNumeric] = useState<Record<NumericKey, string>>({
    max_concurrent_downloads: '',
    chunks_per_file: '',
    max_speed_kbps: '',
    max_concurrent_crawls: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getSettings()
      .then((loaded) => {
        setSettings(loaded)
        setNumeric({
          max_concurrent_downloads: String(loaded.max_concurrent_downloads),
          chunks_per_file: String(loaded.chunks_per_file),
          max_speed_kbps: String(loaded.max_speed_kbps),
          max_concurrent_crawls: String(loaded.max_concurrent_crawls),
        })
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Could not load the settings')
      })
  }, [])

  if (!settings) {
    return (
      <>
        <Masthead>
          <button onClick={onClose}>Back</button>
        </Masthead>
        {error ? (
          <p className="notice" role="alert">
            {error}
          </p>
        ) : null}
      </>
    )
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!settings) return

    const parsed = parseNumeric(numeric)
    if (!parsed) {
      setError('Check the numbers: each one has to sit inside its allowed range.')
      return
    }

    setError(null)
    setSaving(true)
    try {
      await updateSettings({ ...settings, ...parsed })
      onClose()
    } catch (err) {
      // Stays open so the rejected values are still on screen to correct.
      setError(err instanceof Error ? err.message : 'Could not save the settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {/* No "Back" up top: you leave here through Cancel or Save, and two
          exits that do different things invite losing changes. */}
      <Masthead />

      <form onSubmit={handleSubmit}>
        <h1 className="settings__title">Settings</h1>
        <p className="settings__lede">
          These numbers govern the whole engine, not just your downloads: they apply to
          everything the server is fetching right now.
        </p>

        <NumberField
          id="max-concurrent"
          label="Simultaneous downloads"
          hint="How many files the server fetches at once. The rest wait in the queue."
          field="max_concurrent_downloads"
          value={numeric.max_concurrent_downloads}
          onChange={setNumeric}
        />

        <NumberField
          id="max-crawls"
          label="Simultaneous checks"
          hint="How many pasted lists are examined at once, before anything is queued."
          field="max_concurrent_crawls"
          value={numeric.max_concurrent_crawls}
          onChange={setNumeric}
        />

        <NumberField
          id="chunks-per-file"
          label="Chunks per file"
          hint="How many pieces each file is split into so they can be fetched in parallel. More pieces is usually faster, unless the hoster penalises it."
          field="chunks_per_file"
          value={numeric.chunks_per_file}
          onChange={setNumeric}
        />

        <NumberField
          id="max-speed"
          label="Speed limit"
          hint="In KB/s, shared across every download. 0 means no limit."
          field="max_speed_kbps"
          value={numeric.max_speed_kbps}
          onChange={setNumeric}
        />

        {error && (
          <p className="notice settings__error" role="alert">
            {error}
          </p>
        )}

        <div className="settings__actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={saving}>
            Save
          </button>
        </div>
      </form>
    </>
  )
}

interface NumberFieldProps {
  id: string
  label: string
  /** What the number does. The label names; this explains. */
  hint: string
  field: NumericKey
  value: string
  onChange: React.Dispatch<React.SetStateAction<Record<NumericKey, string>>>
}

function NumberField({ id, label, hint, field, value, onChange }: NumberFieldProps) {
  const { min, max } = BOUNDS[field]
  return (
    <div className="settings__field">
      <label className="settings__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="settings__input"
        type="number"
        min={min}
        max={max}
        value={value}
        aria-describedby={`${id}-hint`}
        onChange={(e) => onChange((prev) => ({ ...prev, [field]: e.target.value }))}
      />
      <p className="settings__hint" id={`${id}-hint`}>
        {hint}
      </p>
    </div>
  )
}

/** Returns null if any field is blank or outside the API's accepted range. */
function parseNumeric(raw: Record<NumericKey, string>): Pick<AppSettings, NumericKey> | null {
  const entries = Object.entries(raw) as [NumericKey, string][]
  const parsed = {} as Pick<AppSettings, NumericKey>

  for (const [key, text] of entries) {
    if (text.trim() === '') return null
    const value = Number(text)
    const { min, max } = BOUNDS[key]
    if (!Number.isInteger(value) || value < min || (max !== undefined && value > max)) return null
    parsed[key] = value
  }
  return parsed
}
