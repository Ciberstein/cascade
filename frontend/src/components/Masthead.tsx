import type { ReactNode } from 'react'
import './Masthead.css'

interface Props {
  /** Línea bajo la marca. Solo la pantalla principal la usa: en las de paso
   *  ya se sabe dónde se está, y repetirla sería ruido. */
  note?: string
  /** Navegación de la derecha: cambia según la pantalla. */
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
