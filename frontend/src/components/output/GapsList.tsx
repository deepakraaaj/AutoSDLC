import type { Gap } from '../../types'
import styles from './GapsList.module.css'

export function GapsList({ gaps }: { gaps: Gap[] }) {
  if (!gaps.length) return null

  return (
    <div className={styles.section}>
      <div className={styles.header}>
        <h2>Gaps</h2>
        <span className="badge badge-neutral">{gaps.length}</span>
      </div>
      {gaps.map((g, i) => (
        <div key={i} className={`${styles.item} ${styles[g.severity]}`}>
          <span className={`badge ${severityBadgeClass(g.severity)}`}>{g.severity}</span>
          <span>{g.description}</span>
        </div>
      ))}
    </div>
  )
}

function severityBadgeClass(severity: Gap['severity']): string {
  if (severity === 'blocking') return 'badge-danger'
  if (severity === 'important') return 'badge-warning'
  return 'badge-neutral'
}
