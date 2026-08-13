import { DENIED_MESSAGES } from '../lib/roles'
import { useRole } from '../hooks/useRole'
import { useRoleGatedAction } from '../hooks/useRoleGatedAction'
import { LockIcon } from './icons/LockIcon'
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
  const { canPushToRedmine } = useRole()
  const gatedRedmineClick = useRoleGatedAction(canPushToRedmine, DENIED_MESSAGES.pushToRedmine)

  return (
    <div className={`${styles.bar} ${compact ? styles.compact : ''}`}>
      <button className="btn btn-primary" onClick={onExport}>
        Export
      </button>
      <button
        className={`btn btn-primary ${!canPushToRedmine ? styles.locked : ''}`}
        onClick={gatedRedmineClick(onOpenRedmine)}
        title={canPushToRedmine ? undefined : DENIED_MESSAGES.pushToRedmine}
      >
        {!canPushToRedmine && <LockIcon className={styles.inlineLock} />}
        Redmine
      </button>
      <button className="btn btn-secondary" onClick={onNewRun}>
        New run
      </button>
    </div>
  )
}
