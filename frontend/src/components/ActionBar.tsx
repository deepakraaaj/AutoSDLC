import { useEffect, useRef, useState } from 'react'
import { Download, GitPullRequest, MoreHorizontal, RotateCcw, Server, Settings } from 'lucide-react'
import { DENIED_MESSAGES } from '../lib/roles'
import { useRole } from '../hooks/useRole'
import { useRoleGatedAction } from '../hooks/useRoleGatedAction'
import { LockIcon } from './icons/LockIcon'
import styles from './ActionBar.module.css'

/**
 * Export is the primary action; everything else lives behind the overflow menu.
 * Role gating is unchanged — the same useRoleGatedAction/LockIcon treatment the
 * buttons carried, now on menu items: a denied action still clicks and still
 * explains itself via toast rather than sitting inertly disabled.
 */
export function ActionBar({
  onExport,
  onOpenRedmine,
  onOpenBitbucket,
  onOpenProjectSettings,
  onNewRun,
}: {
  onExport: () => void
  onOpenRedmine: () => void
  onOpenBitbucket: () => void
  onOpenProjectSettings: () => void
  onNewRun: () => void
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const { canPushToRedmine, canPushToBitbucket } = useRole()
  const gatedRedmineClick = useRoleGatedAction(canPushToRedmine, DENIED_MESSAGES.pushToRedmine)
  const gatedBitbucketClick = useRoleGatedAction(canPushToBitbucket, DENIED_MESSAGES.pushToBitbucket)

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  /** Menu items close the menu first, so an action that opens a modal doesn't
   * leave this hanging open behind it. */
  function run(action: () => void) {
    return () => {
      setOpen(false)
      action()
    }
  }

  return (
    <div className={styles.bar}>
      <button className="btn btn-primary" onClick={onExport}>
        <Download aria-hidden="true" />
        Export
      </button>

      <div className={styles.menuWrap} ref={wrapRef}>
        <button
          type="button"
          className={`${styles.menuTrigger} ${open ? styles.menuTriggerOpen : ''}`}
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="More backlog actions"
        >
          <MoreHorizontal aria-hidden="true" />
        </button>

        {open && (
          <div className={styles.menu} role="menu">
            <button
              role="menuitem"
              className={`${styles.menuItem} ${!canPushToRedmine ? styles.locked : ''}`}
              onClick={run(gatedRedmineClick(onOpenRedmine))}
              title={canPushToRedmine ? undefined : DENIED_MESSAGES.pushToRedmine}
            >
              {!canPushToRedmine && <LockIcon className={styles.inlineLock} />}
              <Server aria-hidden="true" />
              Push to Redmine
            </button>
            <button
              role="menuitem"
              className={`${styles.menuItem} ${!canPushToBitbucket ? styles.locked : ''}`}
              onClick={run(gatedBitbucketClick(onOpenBitbucket))}
              title={canPushToBitbucket ? undefined : DENIED_MESSAGES.pushToBitbucket}
            >
              {!canPushToBitbucket && <LockIcon className={styles.inlineLock} />}
              <GitPullRequest aria-hidden="true" />
              Push to Bitbucket
            </button>
            <div className={styles.menuSeparator} />
            <button role="menuitem" className={styles.menuItem} onClick={run(onOpenProjectSettings)}>
              <Settings aria-hidden="true" />
              Project settings
            </button>
            <button role="menuitem" className={styles.menuItem} onClick={run(onNewRun)}>
              <RotateCcw aria-hidden="true" />
              New run
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
