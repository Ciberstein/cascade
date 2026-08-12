import { fileUrl } from './api/packages'
import type { Package } from './types'

/**
 * Tells the browser to fetch whatever just finished.
 *
 * The browser can only save files while the tab is open, so this runs on every
 * dashboard poll. `retrieved` comes from the server and is what stops it
 * repeating: as soon as the request lands the item is marked, and the next poll
 * no longer includes it. The local Set covers the window between firing and the
 * server answering, where an intervening poll would fire it again.
 *
 * Several downloads in a row make the browser ask for permission once
 * ("Download multiple files?"). That belongs to the browser and cannot be
 * avoided from here.
 */
export function autoDownloadFinished(packages: Package[], alreadyTriggered: Set<string>): void {
  for (const pkg of packages) {
    for (const item of pkg.items) {
      const pending =
        item.status === 'completed' &&
        !item.retrieved &&
        !item.file_removed &&
        item.merge_role !== 'audio' &&
        !alreadyTriggered.has(item.id)

      if (!pending) continue

      alreadyTriggered.add(item.id)
      trigger(fileUrl(pkg.id, item.id), item.filename)
    }
  }
}

function trigger(href: string, filename: string): void {
  // A synthetic <a download> rather than window.location: location would
  // navigate the tab if the server ever failed to send Content-Disposition,
  // and several of these can fire in a row.
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}
