import { useEffect, useState } from 'react'
import { ApiError, getIntegrationsStatus } from '../api/client'
import type { IntegrationsStatus } from '../types'
import { Modal } from './Modal'
import styles from './IntegrationsModal.module.css'

const INTEGRATIONS: { key: keyof IntegrationsStatus; label: string; description: string }[] = [
  { key: 'bitbucket', label: 'Bitbucket', description: 'Repo context, PR review, and issue push. Configured server-side.' },
  { key: 'redmine', label: 'Redmine', description: 'Issue push for the backlog. Configured server-side.' },
]

export function IntegrationsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [status, setStatus] = useState<IntegrationsStatus | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setError('')
    getIntegrationsStatus()
      .then(setStatus)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load integration status'))
  }, [open])

  return (
    <Modal open={open} onClose={onClose} title="Integrations" subheader="What's connected on the server — not a place to enter credentials.">
      {error && <div className={styles.errorLine}>{error}</div>}
      {!error && !status && <div className="field-hint">Loading…</div>}
      {status && (
        <div className={styles.list}>
          {INTEGRATIONS.map(({ key, label, description }) => {
            const info = status[key]
            return (
              <div key={key} className={styles.row}>
                <div className={styles.meta}>
                  <div className={styles.name}>{label}</div>
                  <div className={styles.description}>{description}</div>
                </div>
                <span className={`${styles.badge} ${info.connected ? styles.connected : styles.notConnected}`}>
                  {info.connected ? 'Connected' : 'Not connected'}
                </span>
              </div>
            )
          })}
        </div>
      )}
      <div className={styles.actions}>
        <button className="btn btn-secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  )
}
