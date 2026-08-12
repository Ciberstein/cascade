import FlowRail from '../components/FlowRail'
import type { Flow } from '../components/FlowRail'
import Masthead from '../components/Masthead'
import { fileUrl } from '../api/packages'
import StatusBadge from '../components/StatusBadge'
import { formatBytes, percentOf } from '../format'
import type { DownloadItem, Package } from '../types'
import './PackageDetail.css'

interface Props {
  package: Package
  progressByItemId?: Record<string, number>
  onBack: () => void
}

export default function PackageDetail({ package: pkg, progressByItemId = {}, onBack }: Props) {
  return (
    <>
      <Masthead>
        <button onClick={onBack}>Volver</button>
      </Masthead>

      <div className="detail__head">
        <h1 className="detail__title">{pkg.name}</h1>
        <StatusBadge status={pkg.status} />
      </div>

      <p className="detail__where">
        <span className="eyebrow">Carpeta de paso</span>
        <span className="detail__path">{pkg.target_dir}</span>
      </p>

      <ul className="detail__items">
        {pkg.items
          // La pista de audio de una calidad que se está uniendo no se lista:
          // es un medio para conseguir el archivo, no un archivo que el
          // usuario pidió. Su progreso sí cuenta en el riel del paquete.
          .filter((item) => item.merge_role !== 'audio')
          .map((item) => {
            // Misma regla que en la lista: el valor del socket es más fresco
            // que el último checkpoint guardado.
            const downloaded = Math.max(item.downloaded_bytes, progressByItemId[item.id] ?? 0)
            const percent = percentOf(downloaded, item.total_size ?? 0)

            return (
              <li className="item" key={item.id}>
                <FlowRail
                  percent={percent}
                  state={flowOf(item)}
                  label={`Progreso de ${item.filename}`}
                />

                <div className="item__body">
                  <div className="item__head">
                    <span className="item__name" title={item.url}>
                      {item.filename}
                    </span>
                    <StatusBadge status={item.status} />
                  </div>

                  <p className="item__meter">
                    <span className="item__pct">{Math.round(percent)}%</span>
                    <span>
                      {formatBytes(downloaded)} / {formatBytes(item.total_size)}
                    </span>
                  </p>

                  {item.status === 'completed' && item.file_removed && (
                    <p className="item__gone">
                      Ya lo bajaste; el servidor liberó su copia. Volvé a agregar el enlace si lo
                      necesitás otra vez.
                    </p>
                  )}

                  {item.status === 'completed' && !item.file_removed && (
                    // <a download> y no un botón: así lo baja el navegador y
                    // queda en su carpeta de descargas, como cualquier otra.
                    <a
                      className="item__take"
                      href={fileUrl(pkg.id, item.id)}
                      download={item.filename}
                    >
                      Descargar a mi equipo
                    </a>
                  )}

                  {item.error_message && (
                    <p className="notice" role="alert">
                      {item.error_message}
                    </p>
                  )}
                </div>
              </li>
            )
          })}
      </ul>
    </>
  )
}

/** Estado del riel de un archivo suelto. */
function flowOf(item: DownloadItem): Flow {
  if (item.status === 'error') return 'failed'
  // Pausado, cancelado y esperando son lo mismo para el riel: caudal detenido.
  // Pintar un cancelado de rojo lo haría ver como algo que se rompió.
  if (item.status === 'paused' || item.status === 'canceled') return 'stalled'
  if (item.status === 'completed') return item.file_removed ? 'released' : 'done'
  if (item.status === 'running') return 'running'
  // Una espera pedida por el hoster no es un fallo: es caudal detenido.
  return item.retry_after ? 'stalled' : 'queued'
}
