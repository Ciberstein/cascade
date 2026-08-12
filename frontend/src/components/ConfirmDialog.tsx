import Modal from './Modal'

interface Props {
  title: string
  /** What happens if they go ahead, in one sentence. */
  body: string
  /** The button states the action, not "OK": it reads on its own before the click. */
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
          {/* Cancel comes first in the DOM and therefore takes focus on open:
              in a dialog that destroys something, Enter cannot confirm. */}
          <button onClick={onCancel}>Cancel</button>
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
