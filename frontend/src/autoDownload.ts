import { fileUrl } from './api/packages'
import type { Package } from './types'

/**
 * Dispara en el navegador la descarga de lo que acaba de terminar.
 *
 * El navegador solo puede guardar archivos con la pestaña abierta, así que
 * esto corre en cada sondeo del dashboard. `retrieved` viene del servidor y es
 * lo que evita repetirlo: en cuanto la request llega, el item queda marcado y
 * el próximo sondeo ya no lo incluye. El Set local cubre la ventana entre que
 * se dispara y que el servidor contesta, donde un sondeo intermedio lo
 * dispararía de nuevo.
 *
 * Bajar varios seguidos hace que el navegador pida permiso una vez ("¿Descargar
 * varios archivos?"). Es del navegador, no algo que se pueda evitar desde acá.
 */
export function autoDownloadFinished(packages: Package[], alreadyTriggered: Set<string>): void {
  for (const pkg of packages) {
    for (const item of pkg.items) {
      const pendiente =
        item.status === 'completed' &&
        !item.retrieved &&
        !item.file_removed &&
        item.merge_role !== 'audio' &&
        !alreadyTriggered.has(item.id)

      if (!pendiente) continue

      alreadyTriggered.add(item.id)
      trigger(fileUrl(pkg.id, item.id), item.filename)
    }
  }
}

function trigger(href: string, filename: string): void {
  // Un <a download> sintético y no window.location: location navegaría la
  // pestaña si el servidor no mandara Content-Disposition, y acá pueden
  // dispararse varios seguidos.
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}
