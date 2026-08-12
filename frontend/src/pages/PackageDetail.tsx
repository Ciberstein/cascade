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
        <button onClick={onBack}>Back</button>
      </Masthead>

      <div className="detail__head">
        <h1 className="detail__title">{pkg.name}</h1>
        <StatusBadge status={pkg.status} />
      </div>

      <p className="detail__where">
        <span className="eyebrow">Staging folder</span>
        <span className="detail__path">{pkg.target_dir}</span>
      </p>

      <ul className="detail__items">
        {pkg.items
          // The audio track of a quality being merged isn't listed: it is a
          // means to get the file, not a file the user asked for. Its progress
          // does count towards the package rail.
          .filter((item) => item.merge_role !== 'audio')
          .map((item) => {
            // Same rule as in the list: the socket value is fresher than the
            // last checkpoint written to the database.
            const downloaded = Math.max(item.downloaded_bytes, progressByItemId[item.id] ?? 0)
            const percent = percentOf(downloaded, item.total_size ?? 0)

            return (
              <li className="item" key={item.id}>
                <FlowRail
                  percent={percent}
                  state={flowOf(item)}
                  label={`Progress of ${item.filename}`}
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
                      You already took this one; the server let its copy go. Add the link again if
                      you need it once more.
                    </p>
                  )}

                  {item.status === 'completed' && !item.file_removed && (
                    // <a download> rather than a button: this way the browser
                    // performs the download and it lands in its usual folder.
                    <a
                      className="item__take"
                      href={fileUrl(pkg.id, item.id)}
                      download={item.filename}
                    >
                      Download to my computer
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

/** The rail state for a single file. */
function flowOf(item: DownloadItem): Flow {
  if (item.status === 'error') return 'failed'
  // Paused, canceled and waiting are the same thing to the rail: stopped flow.
  // Painting a canceled item red would make it look like something broke.
  if (item.status === 'paused' || item.status === 'canceled') return 'stalled'
  if (item.status === 'completed') return item.file_removed ? 'released' : 'done'
  if (item.status === 'running') return 'running'
  // A wait the hoster asked for is not a failure: it is stopped flow.
  return item.retry_after ? 'stalled' : 'queued'
}
