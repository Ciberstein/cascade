import { useState } from 'react'
import Modal from './Modal'

interface Props {
  /** Current name: arrives written and selected, as window.prompt used to do. */
  initial: string
  onConfirm: (name: string) => void
  onCancel: () => void
}

export default function RenameDialog({ initial, onConfirm, onCancel }: Props) {
  const [name, setName] = useState(initial)
  const trimmed = name.trim()

  return (
    <Modal
      title="Rename package"
      onClose={onCancel}
      actions={
        <>
          <button onClick={onCancel}>Cancel</button>
          {/* The API rejects an empty name; no point travelling to fail, and a
              dead button explains why better than an error would. */}
          <button className="primary" disabled={trimmed === ''} onClick={() => onConfirm(trimmed)}>
            Save name
          </button>
        </>
      }
    >
      <div className="modal__field">
        <label className="eyebrow" htmlFor="rename-name">
          Package name
        </label>
        <input
          id="rename-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && trimmed !== '') onConfirm(trimmed)
          }}
        />
      </div>
    </Modal>
  )
}
