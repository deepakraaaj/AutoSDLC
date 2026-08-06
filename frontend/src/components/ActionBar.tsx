import styles from './ActionBar.module.css'

export function ActionBar({
  onExport,
  onOpenRedmine,
  onNewRun,
  compact = false,
}: {
  onExport: () => void
  onOpenRedmine: () => void
  onNewRun: () => void
  compact?: boolean
}) {
  return (
    <div className={`${styles.bar} ${compact ? styles.compact : ''}`}>
      <button className="btn btn-primary" onClick={onExport}>
        Export
      </button>
      <button className="btn btn-primary" onClick={onOpenRedmine}>
        Redmine
      </button>
      <button className="btn btn-secondary" onClick={onNewRun}>
        New run
      </button>
    </div>
  )
}
