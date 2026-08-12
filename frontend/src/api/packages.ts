import { apiFetch } from './client'
import type { Package, PackageAction } from '../types'

export function listPackages(): Promise<Package[]> {
  return apiFetch('/packages')
}

export function createPackage(name: string, urls: string[]): Promise<Package> {
  return apiFetch('/packages', { method: 'POST', body: JSON.stringify({ name, urls }) })
}

/** Resuming is `queued` - the scheduler picks the package back up on its next tick. */
export function updatePackageStatus(id: string, status: PackageAction): Promise<Package> {
  return apiFetch(`/packages/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
}

export function renamePackage(id: string, name: string): Promise<Package> {
  return apiFetch(`/packages/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) })
}

/** Takes the package off the list. Files already downloaded stay on disk. */
export function deletePackage(id: string): Promise<void> {
  return apiFetch(`/packages/${id}`, { method: 'DELETE' })
}

/**
 * The URL the browser downloads the file from.
 *
 * Deliberately not routed through apiFetch: it is used as an href so the
 * browser performs the download and it lands in its usual folder. Fetching it
 * would leave the bytes in memory, which is the opposite of the point.
 */
export function fileUrl(packageId: string, itemId: string): string {
  return `/packages/${packageId}/items/${itemId}/file`
}
