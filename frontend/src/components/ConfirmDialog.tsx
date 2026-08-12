import Modal from './Modal'

interface Props {
  title: string
  /** Qué pasa si sigue adelante, en una frase. */
  body: string
  /** El botón dice la acción, no "Aceptar": se lee solo antes de hacer clic. */
  confirmLabel: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmDialog({
  title,
  body,
  confirmLabel,
  destructive = false,
  onConfirm,
  onCancel,
}: Props) {
  return (
    <Modal
      title={title}
      tone={destructive ? 'fail' : 'flow'}
      onClose={onCancel}
      actions={
        <>
          {/* Cancelar va primero en el DOM y por eso se lleva el foco al abrir:
              en un diálogo que destruye algo, Enter no puede confirmar de una. */}
          <button onClick={onCancel}>Cancelar</button>
          <button className={destructive ? 'destructive' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </>
      }
    >
      <p className="modal__text">{body}</p>
    </Modal>
  )
}
