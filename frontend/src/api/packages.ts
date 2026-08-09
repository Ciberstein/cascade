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

/** Saca el paquete de la lista. Los archivos ya descargados quedan en disco. */
export function deletePackage(id: string): Promise<void> {
  return apiFetch(`/packages/${id}`, { method: 'DELETE' })
}

/**
 * URL desde la que el navegador se baja el archivo.
 *
 * No pasa por apiFetch a propósito: se usa como href, para que la descarga la
 * haga el navegador y termine en su carpeta de siempre. Traerla por fetch la
 * dejaría en memoria, que es justo lo contrario de lo que se quiere.
 */
export function fileUrl(packageId: string, itemId: string): string {
  return `/packages/${packageId}/items/${itemId}/file`
}
