import ProgressBar from '../components/ProgressBar'
import { fileUrl } from '../api/packages'
import StatusBadge from '../components/StatusBadge'
import { formatBytes, percentOf } from '../format'
import type { Package } from '../types'
import './PackageDetail.css'

interface Props {
  package: Package
  progressByItemId?: Record<string, number>
  onBack: () => void
}

export default function PackageDetail({ package: pkg, progressByItemId = {}, onBack }: Props) {
  return (
    <div className="detail">
      <div className="detail__header">
        <button onClick={onBack}>Volver</button>
        <StatusBadge status={pkg.status} />
      </div>

      <div>
        <h1 className="detail__title">{pkg.name}</h1>
        <p className="detail__path">{pkg.target_dir}</p>
      </div>

      <ul className="detail__items">
        {pkg.items.map((item) => {
          // Same rule as PackageRow: the socket value is fresher than the
          // byte count last checkpointed to the DB.
          const downloaded = Math.max(item.downloaded_bytes, progressByItemId[item.id] ?? 0)
          const percent = percentOf(downloaded, item.total_size ?? 0)

          return (
            <li className="detail__item" key={item.id}>
              <div className="detail__item-header">
                <span className="detail__filename" title={item.url}>
                  {item.filename}
                </span>
                <StatusBadge status={item.status} />
              </div>

              <ProgressBar
                percent={percent}
                caption={`${formatBytes(downloaded)} / ${formatBytes(item.total_size)}`}
              />

              {item.status === 'completed' && (
                // <a download> y no un botón: así lo baja el navegador y queda
                // en su carpeta de descargas, como cualquier otra descarga.
                <a className="detail__download" href={fileUrl(pkg.id, item.id)} download={item.filename}>
                  Descargar a mi equipo
                </a>
              )}

              {item.error_message && (
                <p className="detail__error" role="alert">
                  {item.error_message}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
