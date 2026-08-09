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
