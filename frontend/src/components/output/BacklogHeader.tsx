import type { GenerationOutput } from '../../types'
import { scoreTone, totalEstimateHours } from '../../lib/format'
import { ActionBar } from '../ActionBar'
import styles from './BacklogHeader.module.css'

const TONE_COLOR: Record<ReturnType<typeof scoreTone>, string> = {
  success: 'var(--success)',
  warning: 'var(--warning)',
  danger: 'var(--danger)',
}

/**
 * The backlog page's one header row: which backlog, how big, and what to do with it.
 *
 * The counts come from the same fields Dashboard read, rendered as a quiet inline run
 * instead of six bordered stat tiles — on this page they are orientation, not the
 * subject. The subject is the backlog below.
 */
export function BacklogHeader({
  output,
  title,
  quality,
  onOpenQuality,
  onExport,
  onOpenRedmine,
  onOpenBitbucket,
  onOpenProjectSettings,
  onNewRun,
  onGenerateTasks,
}: {
  output: GenerationOutput
  title: string
  /** Overall quality score, or null when the run produced no metrics. */
  quality: number | null
  onOpenQuality: () => void
  onExport: () => void
  onOpenRedmine: () => void
  onOpenBitbucket: () => void
  onOpenProjectSettings: () => void
  onNewRun: () => void
  onGenerateTasks?: () => void
}) {
  const stats: { label: string; value: number | string }[] = [
    { label: 'epics', value: output.epics.length },
    { label: 'stories', value: output.stories.length },
    { label: 'tasks', value: output.tasks.length },
    { label: 'hrs', value: totalEstimateHours(output.tasks) },
  ]

  return (
    <div className={styles.header}>
      <h1 className={styles.title}>{title}</h1>

      <div className={styles.stats}>
        {stats.map((s) => (
          <span key={s.label} className={styles.stat}>
            <span className={styles.statValue}>{s.value}</span>
            {s.label}
          </span>
        ))}
      </div>

      <div className={styles.spacer} />

      {output.tasks.length === 0 && onGenerateTasks && (
        <button className="btn btn-primary btn-sm" onClick={onGenerateTasks} style={{ marginRight: 'var(--space-2)' }}>
          Generate Tasks & Tests
        </button>
      )}

      {quality != null && (
        <button type="button" className={styles.qualityButton} onClick={onOpenQuality}>
          <span className={styles.qualityDot} style={{ background: TONE_COLOR[scoreTone(quality)] }} />
          Quality {quality}%
        </button>
      )}

      <ActionBar
        onExport={onExport}
        onOpenRedmine={onOpenRedmine}
        onOpenBitbucket={onOpenBitbucket}
        onOpenProjectSettings={onOpenProjectSettings}
        onNewRun={onNewRun}
      />
    </div>
  )
}
