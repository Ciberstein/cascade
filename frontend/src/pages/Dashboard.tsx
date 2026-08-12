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
 * Phase 1 had three screens behind one auth gate, so this stays as state rather
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
 * What the user is being asked.
 *
 * The dialogs live here rather than in the row: the row announces the
 * intention, and the only place that knows what is about to happen to which
 * package is the one holding the list and the API calls.
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
  // Covers the window between firing a download and the server marking it
  // retrieved, where an intervening poll would fire it again.
  const triggered = useRef<Set<string>>(new Set())

  const { progressByItemId } = useProgressSocket()

  const refresh = useCallback(async () => {
    try {
      const fetched = await listPackages()
      setPackages(fetched)
      // The moment it finishes the browser takes it: the server is a place to
      // pass through, and it frees the file as soon as it hands it over.
      autoDownloadFinished(fetched, triggered.current)
      setError(null)
    } catch (e) {
      // A failed poll is usually the backend restarting. Keep the last known
      // list on screen and say so, rather than blanking the dashboard.
      setError(e instanceof Error ? e.message : 'Could not load the package list')
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
      // It stays on the same screen: switching views would throw away the
      // links that were just pasted.
      setCreateError(e instanceof Error ? e.message : 'Could not check those links')
    } finally {
      setCreating(false)
    }
  }

  async function handleRename(id: string, name: string) {
    try {
      await renamePackage(id, name)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not rename the package')
    }
  }

  async function handleDelete(id: string) {
    try {
      await deletePackage(id)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove the package')
    }
  }

  async function handleStatusChange(id: string, status: PackageAction) {
    try {
      await updatePackageStatus(id, status)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update the package')
    }
  }

  if (view.name === 'account') {
    return (
      <Account
        onClose={() => setView({ name: 'list' })}
        onIdentityChanged={() => {
          // Signing in changes the owner token: the list that was on screen
          // is no longer this browser's.
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
      <Masthead note="Paste a link, get the file. The server keeps nothing.">
        <button onClick={() => setView({ name: 'account' })}>Account</button>
        <button onClick={() => setView({ name: 'settings' })}>Settings</button>
      </Masthead>

      {/* Pasting a link is the only thing to do here, so it is on screen and
          not behind a button that opens a dialog. */}
      <LinkIntake
        onSubmit={(urls) => void handleAnalyze(urls)}
        submitting={creating}
        error={createError}
      />

      <section>
        <div className="channel__head">
          {/* The design carries the channel metaphor; the words name what the
              user recognises. */}
          <h1 className="eyebrow">Your downloads</h1>
          {packages.length > 0 && (
            <span className="channel__count">
              {packages.length} package{packages.length === 1 ? '' : 's'}
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
              No downloads yet. Paste a link up there.
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
          title="Remove from list"
          // "Remove" can sound like it deletes the file, and it doesn't:
          // nothing touches what already reached the user's machine.
          body={`"${asking.name}" leaves your list. Whatever you already downloaded stays where it is.`}
          // The full action, so it never collides with the row's own "Remove"
          // sitting behind the dialog.
          confirmLabel="Remove from list"
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
