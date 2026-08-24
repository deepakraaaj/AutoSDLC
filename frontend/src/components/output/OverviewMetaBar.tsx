import { Clock3, PanelRight, Sparkles } from 'lucide-react'
import type { GenerationOutput } from '../../types'
import { formatDate, formatDuration } from '../../lib/format'
import styles from './OverviewMetaBar.module.css'

export function OverviewMetaBar({
  output,
  railOpen,
  onToggleRail,
}: {
  output: GenerationOutput
  railOpen: boolean
  onToggleRail: () => void
}) {
  const seconds = output.metrics?.generation_seconds

  return (
    <div className={styles.bar}>
      <div className={styles.facts}>
        {output.created_at && (
          <span className={styles.fact}>
            <Clock3 aria-hidden="true" />
            {formatDate(output.created_at)}
          </span>
        )}
        {seconds != null && (
          <span className={styles.fact}>
            <Sparkles aria-hidden="true" />
            Generated in {formatDuration(seconds)}
          </span>
        )}
      </div>

      <div className={styles.spacer} />

      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.iconBtn} ${railOpen ? styles.iconBtnPressed : ''}`}
          onClick={onToggleRail}
          aria-label={railOpen ? 'Hide quality panel' : 'Show quality panel'}
          aria-pressed={railOpen}
          title={railOpen ? 'Hide quality panel' : 'Show quality panel'}
        >
          <PanelRight aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
