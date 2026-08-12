import { useState } from 'react'
import Modal from './Modal'

interface Props {
  /** Nombre actual: entra escrito y seleccionado, como hacía window.prompt. */
  initial: string
  onConfirm: (name: string) => void
  onCancel: () => void
}

export default function RenameDialog({ initial, onConfirm, onCancel }: Props) {
  const [name, setName] = useState(initial)
  const trimmed = name.trim()

  return (
    <Modal
      title="Renombrar paquete"
      onClose={onCancel}
      actions={
        <>
          <button onClick={onCancel}>Cancelar</button>
          {/* La API rechaza un nombre vacío; no vale la pena viajar para que
              falle, y un botón muerto explica el porqué mejor que un error. */}
          <button className="primary" disabled={trimmed === ''} onClick={() => onConfirm(trimmed)}>
            Guardar nombre
          </button>
        </>
      }
    >
      <div className="modal__field">
        <label className="eyebrow" htmlFor="rename-name">
          Nombre del paquete
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
