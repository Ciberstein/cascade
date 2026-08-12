import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import './Modal.css'

interface Props {
  title: string
  /** Pinta el riel: 'fail' cuando la acción hace perder algo. */
  tone?: 'flow' | 'fail'
  /** Cancelar: Escape, clic en el fondo, o el botón de descarte. */
  onClose: () => void
  children: ReactNode
  actions: ReactNode
}

const FOCUSABLE = 'button:not(:disabled), input:not(:disabled), select, textarea, a[href]'

/**
 * Diálogo propio, en el lenguaje de la app.
 *
 * Reemplaza a window.confirm y window.prompt: los diálogos del navegador se
 * ven distinto en cada sistema, no se pueden escribir con la voz del producto
 * y en Chrome traen una casilla para silenciarlos que deja la app sin forma de
 * preguntar nada.
 */
export default function Modal({ title, tone = 'flow', onClose, children, actions }: Props) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    // A dónde vuelve el foco al cerrar: sin esto, quien abrió el diálogo con el
    // teclado queda al principio de la página.
    const opener = document.activeElement as HTMLElement | null

    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
    // Igual que hacía window.prompt: el texto entra seleccionado, así escribir
    // lo reemplaza y no hay que borrarlo a mano.
    if (first instanceof HTMLInputElement) first.select()

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = previousOverflow
      opener?.focus?.()
    }
  }, [])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose()
      return
    }
    if (e.key !== 'Tab') return

    // Ciclo cerrado de tabulación: sin esto el foco se va a la página de atrás,
    // que está tapada, y no se ve dónde quedó.
    const items = [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])]
    if (items.length === 0) return

    const edge = e.shiftKey ? items[0] : items[items.length - 1]
    if (document.activeElement === edge) {
      e.preventDefault()
      ;(e.shiftKey ? items[items.length - 1] : items[0]).focus()
    }
  }

  return (
    <div
      className="modal"
      onKeyDown={handleKeyDown}
      // mousedown y no click: si se arrastra para seleccionar texto dentro del
      // panel y se suelta afuera, un click cerraría el diálogo.
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="modal__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panel}
      >
        <div className={`modal__rail modal__rail--${tone}`} aria-hidden="true" />
        <div className="modal__body">
          <h2 className="modal__title" id={titleId}>
            {title}
          </h2>
          {children}
          <div className="modal__actions">{actions}</div>
        </div>
      </div>
    </div>
  )
}
