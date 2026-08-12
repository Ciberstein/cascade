import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import './Modal.css'

interface Props {
  title: string
  /** Paints the rail: 'fail' when the action loses something. */
  tone?: 'flow' | 'fail'
  /** Dismissal: Escape, a click on the backdrop, or the cancel button. */
  onClose: () => void
  children: ReactNode
  actions: ReactNode
}

const FOCUSABLE = 'button:not(:disabled), input:not(:disabled), select, textarea, a[href]'

/**
 * Our own dialog, in the app's language.
 *
 * Replaces window.confirm and window.prompt: the browser's dialogs look
 * different on every system, cannot be written in the product's voice, and in
 * Chrome carry a checkbox to silence them that leaves the app with no way to
 * ask anything at all.
 */
export default function Modal({ title, tone = 'flow', onClose, children, actions }: Props) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    // Where focus returns on close: without this, whoever opened the dialog
    // from the keyboard ends up back at the top of the page.
    const opener = document.activeElement as HTMLElement | null

    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
    // Same as window.prompt did: the text arrives selected, so typing replaces
    // it and nobody has to clear it by hand.
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

    // Closed tab cycle: without it focus walks off into the page behind, which
    // is covered, and there is no way to see where the cursor went.
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
      // mousedown rather than click: if you drag to select text inside the
      // panel and release outside it, a click would close the dialog.
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
