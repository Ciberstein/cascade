import { useCallback, useEffect, useRef, useState } from 'react'
import { deletePackage, listPackages, renamePackage, updatePackageStatus } from '../api/packages'
import { createCrawlJob } from '../api/crawl'
import { autoDownloadFinished } from '../autoDownload'
import { useProgressSocket } from '../ws/useProgressSocket'
import PackageRow from '../components/PackageRow'
import LinkIntake from '../components/LinkIntake'
import Masthead from '../components/Masthead'
import ConfirmDialog from '../components/ConfirmDialog'
import RenameDialog from '../components/RenameDialog'
import PackageDetail from './PackageDetail'
import SettingsPage from './Settings'
import Account from './Account'
import LinkGrabber from './LinkGrabber'
import type { Package, PackageAction } from '../types'
import './Dashboard.css'

/**
 * Which screen is showing.
 *
 * Fase 1 has three screens behind one auth gate, so this stays as state rather
 * than pulling in a router. Detail holds an id (not the package object) so the
 * background poll keeps feeding it fresh data.
 */
type View =
  | { name: 'list' }
  | { name: 'detail'; packageId: string }
  | { name: 'settings' }
  | { name: 'grabber'; jobId: string }
  | { name: 'account' }

/**
 * How often the package list is refetched.
 *
 * The WS feed only carries byte counts, so status transitions (queued ->
 * running -> completed, or an item erroring out) are only visible through a
 * refetch. Progress itself stays on the socket - this poll is deliberately
 * slower than the ~500ms broadcast interval.
 */
const REFRESH_INTERVAL_MS = 3000

/**
 * Lo que se le está preguntando al usuario.
 *
 * Los diálogos viven acá y no en la fila: la fila avisa la intención, y el
 * único lugar que sabe qué se está por hacer con qué paquete es el que tiene
 * la lista y las llamadas a la API.
 */
type Ask =
  | { kind: 'delete'; id: string; name: string }
  | { kind: 'rename'; id: string; name: string }

export default function Dashboard() {
  const [packages, setPackages] = useState<Package[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [view, setView] = useState<View>({ name: 'list' })
  const [asking, setAsking] = useState<Ask | null>(null)
  // Cubre la ventana entre que se dispara una descarga y que el servidor la
  // marca retirada, donde un sondeo intermedio la dispararía de nuevo.
  const triggered = useRef<Set<string>>(new Set())

  const { progressByItemId } = useProgressSocket()

  const refresh = useCallback(async () => {
    try {
      const fetched = await listPackages()
      setPackages(fetched)
      // Apenas termina, se lo lleva el navegador: el servidor es un lugar de
      // paso y lo libera en cuanto lo entrega.
      autoDownloadFinished(fetched, triggered.current)
      setError(null)
    } catch (e) {
      // A failed poll is usually the backend restarting. Keep the last known
      // list on screen and say so, rather than blanking the dashboard.
      setError(e instanceof Error ? e.message : 'No se pudo cargar la lista de paquetes')
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), REFRESH_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [refresh])

  async function handleAnalyze(urls: string[]) {
    setCreating(true)
    setCreateError(null)
    try {
      const job = await createCrawlJob(urls.join('\n'))
      setView({ name: 'grabber', jobId: job.id })
    } catch (e) {
      // Se queda en la misma pantalla: cambiar de vista tiraría los enlaces
      // recién pegados.
      setCreateError(e instanceof Error ? e.message : 'No se pudo analizar los enlaces')
    } finally {
      setCreating(false)
    }
  }

  async function handleRename(id: string, name: string) {
    try {
      await renamePackage(id, name)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo renombrar el paquete')
    }
  }

  async function handleDelete(id: string) {
    try {
      await deletePackage(id)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo eliminar el paquete')
    }
  }

  async function handleStatusChange(id: string, status: PackageAction) {
    try {
      await updatePackageStatus(id, status)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo actualizar el paquete')
    }
  }

  if (view.name === 'account') {
    return (
      <Account
        onClose={() => setView({ name: 'list' })}
        onIdentityChanged={() => {
          // Iniciar sesión cambia el token de dueño: la lista que se estaba
          // mostrando ya no es la de este navegador.
          setPackages([])
          setView({ name: 'list' })
          void refresh()
        }}
      />
    )
  }

  if (view.name === 'settings') {
    return <SettingsPage onClose={() => setView({ name: 'list' })} />
  }

  if (view.name === 'grabber') {
    return (
      <LinkGrabber
        jobId={view.jobId}
        onBack={() => setView({ name: 'list' })}
        onDone={() => {
          setView({ name: 'list' })
          void refresh()
        }}
      />
    )
  }

  if (view.name === 'detail') {
    const selected = packages.find((p) => p.id === view.packageId)
    // Falls through to the list if the package is gone (deleted elsewhere, or
    // the first poll hasn't answered yet) rather than rendering a dead screen.
    if (selected) {
      return (
        <PackageDetail
          package={selected}
          progressByItemId={progressByItemId}
          onBack={() => setView({ name: 'list' })}
        />
      )
    }
  }

  return (
    <>
      <Masthead note="El archivo pasa por el servidor y no se queda.">
        <button onClick={() => setView({ name: 'account' })}>Cuenta</button>
        <button onClick={() => setView({ name: 'settings' })}>Configuración</button>
      </Masthead>

      {/* Pegar un enlace es lo único que hay que hacer acá, así que está a la
          vista y no detrás de un botón que abre un diálogo. */}
      <LinkIntake
        onSubmit={(urls) => void handleAnalyze(urls)}
        submitting={creating}
        error={createError}
      />

      <section>
        <div className="channel__head">
          {/* La metáfora del canal la sostiene el diseño; las palabras nombran
              lo que el usuario reconoce. */}
          <h1 className="eyebrow">Tus descargas</h1>
          {packages.length > 0 && (
            <span className="channel__count">
              {packages.length} paquete{packages.length === 1 ? '' : 's'}
            </span>
          )}
        </div>

        {error && (
          <p className="notice channel__error" role="alert">
            {error}
          </p>
        )}

        {loaded && packages.length === 0 ? (
          <div className="channel__empty">
            <div className="channel__empty-rail" aria-hidden="true" />
            <p className="channel__empty-text">
              No hay descargas todavía. Pegá un enlace acá arriba.
            </p>
          </div>
        ) : (
          packages.map((pkg) => (
            <PackageRow
              key={pkg.id}
              package={pkg}
              progressByItemId={progressByItemId}
              onPause={(id) => void handleStatusChange(id, 'paused')}
              onResume={(id) => void handleStatusChange(id, 'queued')}
              onCancel={(id) => void handleStatusChange(id, 'canceled')}
              onRename={(id) => setAsking({ kind: 'rename', id, name: pkg.name })}
              onDelete={(id) => setAsking({ kind: 'delete', id, name: pkg.name })}
              onOpen={(id) => setView({ name: 'detail', packageId: id })}
            />
          ))
        )}
      </section>

      {asking?.kind === 'delete' && (
        <ConfirmDialog
          title="Quitar de la lista"
          // "Eliminar" suena a que borra el archivo, y no lo hace: lo que ya
          // llegó al equipo del usuario no lo toca nadie.
          body={`«${asking.name}» sale de tu lista. Lo que ya bajaste a tu equipo se queda donde está.`}
          confirmLabel="Quitar"
          destructive
          onConfirm={() => {
            void handleDelete(asking.id)
            setAsking(null)
          }}
          onCancel={() => setAsking(null)}
        />
      )}

      {asking?.kind === 'rename' && (
        <RenameDialog
          initial={asking.name}
          onConfirm={(name) => {
            void handleRename(asking.id, name)
            setAsking(null)
          }}
          onCancel={() => setAsking(null)}
        />
      )}
    </>
  )
}
