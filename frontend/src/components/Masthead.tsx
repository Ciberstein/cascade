import type { ReactNode } from 'react'
import './Masthead.css'

interface Props {
  /** Line under the wordmark. Only the main screen uses it: on the screens you
   *  pass through you already know where you are, and repeating it is noise. */
  note?: string
  /** Navigation on the right; changes per screen. */
  children?: ReactNode
}

export default function Masthead({ note, children }: Props) {
  return (
    <header className="masthead">
      <div>
        <div className="masthead__brand">
          <span className="masthead__rail" aria-hidden="true" />
          <span className="masthead__word">Cascade</span>
        </div>
        {note && <p className="masthead__note">{note}</p>}
      </div>
      {children && <nav className="masthead__nav">{children}</nav>}
    </header>
  )
}
