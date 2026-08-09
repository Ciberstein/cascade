import { useCallback, useEffect, useRef, useState } from 'react'
import { deletePackage, listPackages, renamePackage, updatePackageStatus } from '../api/packages'
import { createCrawlJob } from '../api/crawl'
import { autoDownloadFinished } from '../autoDownload'
import { useProgressSocket } from '../ws/useProgressSocket'
import PackageRow from '../components/PackageRow'
import AddLinksModal from '../components/AddLinksModal'
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

export default function Dashboard() {
  const [packages, setPackages] = useState<Package[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [view, setView] = useState<View>({ name: 'list' })
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
      setShowModal(false)
      setView({ name: 'grabber', jobId: job.id })
    } catch (e) {
      // El modal queda abierto: cerrarlo tiraría los enlaces recién pegados.
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
    // Se avisa que el archivo queda: "eliminar" suena a que borra el archivo,
    // y no lo hace.
    if (!window.confirm('¿Quitar este paquete de la lista? Los archivos ya descargados no se borran.')) {
      return
    }
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
    return (
      <SettingsPage onClose={() => setView({ name: 'list' })} />
    )
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
    <div className="dashboard">
      <div className="dashboard__toolbar">
        <h1 className="dashboard__title">Descargas</h1>
        <div className="dashboard__toolbar-actions">
          <button onClick={() => setView({ name: 'account' })}>Cuenta</button>
          <button onClick={() => setView({ name: 'settings' })}>Configuración</button>
          <button className="dashboard__primary" onClick={() => setShowModal(true)}>
            Agregar enlaces
          </button>
        </div>
      </div>

      {error && (
        <p className="dashboard__error" role="alert">
          {error}
        </p>
      )}

      {loaded && packages.length === 0 ? (
        <p className="dashboard__empty">No hay descargas todavía. Agregá enlaces para empezar.</p>
      ) : (
        <div className="dashboard__list">
          {packages.map((pkg) => (
            <PackageRow
              key={pkg.id}
              package={pkg}
              progressByItemId={progressByItemId}
              onPause={(id) => void handleStatusChange(id, 'paused')}
              onResume={(id) => void handleStatusChange(id, 'queued')}
              onCancel={(id) => void handleStatusChange(id, 'canceled')}
              onRename={(id, name) => void handleRename(id, name)}
              onDelete={(id) => void handleDelete(id)}
              onOpen={(id) => setView({ name: 'detail', packageId: id })}
            />
          ))}
        </div>
      )}

      {showModal && (
        <AddLinksModal
          onSubmit={(urls) => void handleAnalyze(urls)}
          onClose={() => {
            setShowModal(false)
            setCreateError(null)
          }}
          submitting={creating}
          error={createError}
        />
      )}
    </div>
  )
}
