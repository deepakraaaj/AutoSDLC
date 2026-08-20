import styles from './GenerationNotice.module.css'

export function GenerationNotice({ onViewBacklog }: { onViewBacklog: () => void }) {
  return (
    <div className={styles.notice} role="status">
      <span className={styles.pulse} aria-hidden="true" />
      <div>
        <strong>Generating your backlog</strong>
        <p>You can keep working here. Generation continues in the background.</p>
      </div>
      <button className="btn btn-secondary btn-sm" onClick={onViewBacklog}>View live progress</button>
    </div>
  )
}
