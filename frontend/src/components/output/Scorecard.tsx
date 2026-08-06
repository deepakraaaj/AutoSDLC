import type { OverallMetrics } from '../../types'
import { scoreTone } from '../../lib/format'
import styles from './Scorecard.module.css'

const FILL_CLASS: Record<ReturnType<typeof scoreTone>, string> = {
  success: styles.fillSuccess,
  warning: styles.fillWarning,
  danger: styles.fillDanger,
}

function Bar({ label, score }: { label: string; score: number }) {
  const tone = scoreTone(score)
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <div className={styles.barTrack}>
        <div className={`${styles.barFill} ${FILL_CLASS[tone]}`} style={{ width: `${score}%` }} />
      </div>
      <span className={`${styles.val} ${styles[tone]}`}>{score}</span>
    </div>
  )
}

export function Scorecard({ metrics, onCopy }: { metrics: OverallMetrics; onCopy: () => void }) {
  const gapTone = metrics.gap_count === 0 ? 'success' : metrics.gap_count <= 3 ? 'warning' : 'danger'

  return (
    <div className={`card ${styles.card}`}>
      <div className={styles.header}>
        <h2>Quality</h2>
        <button className="btn btn-ghost btn-sm" onClick={onCopy}>
          Copy
        </button>
      </div>
      <div className={styles.grid}>
        <div>
          <h3 className={styles.groupTitle}>Stories</h3>
          <Bar label="Specificity" score={metrics.story_metrics.specificity_score} />
          <Bar label="Testability" score={metrics.story_metrics.testability_score} />
          <Bar label="Sizing" score={metrics.story_metrics.sizing_score} />
          <Bar label="Edge cases" score={metrics.story_metrics.edge_case_score} />
        </div>
        <div>
          <h3 className={styles.groupTitle}>Tasks</h3>
          <Bar label="Clarity" score={metrics.task_metrics.clarity_score} />
          <Bar label="Definition of done" score={metrics.task_metrics.definition_of_done_score} />
          <Bar label="Estimates" score={metrics.task_metrics.estimate_score} />
          <Bar label="Dependencies" score={metrics.task_metrics.dependency_score} />
        </div>
      </div>
      <div className={styles.overallRow}>
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[scoreTone(metrics.story_metrics.overall)]}`}>
            {metrics.story_metrics.overall}%
          </div>
          <div className={styles.overallLabel}>Story quality</div>
        </div>
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[scoreTone(metrics.task_metrics.overall)]}`}>
            {metrics.task_metrics.overall}%
          </div>
          <div className={styles.overallLabel}>Task quality</div>
        </div>
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[scoreTone(metrics.coverage_score)]}`}>
            {metrics.coverage_score}%
          </div>
          <div className={styles.overallLabel}>Coverage</div>
        </div>
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[gapTone]}`}>{metrics.gap_count}</div>
          <div className={styles.overallLabel}>Gaps found</div>
        </div>
      </div>
      {metrics.confidence_summary && <div className={styles.confidenceNote}>{metrics.confidence_summary}</div>}
    </div>
  )
}
