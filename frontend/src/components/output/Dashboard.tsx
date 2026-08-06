import type { GenerationOutput } from '../../types'
import { totalEstimateHours } from '../../lib/format'
import styles from './Dashboard.module.css'

const QUALITY_COLOR: Record<string, string> = {
  high: 'var(--success)',
  medium: 'var(--warning)',
  low: 'var(--danger)',
}

/**
 * One stats bar, not two near-duplicate ones. The original UI had a
 * "Dashboard" widget (epics/stories/tasks/quality/input-quality) sitting
 * directly above a "Sprint Summary" widget (stories/tasks/hours/quality) —
 * the same three numbers shown twice a few pixels apart. Merged here.
 */
export function Dashboard({ output, compact = false }: { output: GenerationOutput; compact?: boolean }) {
  const quality = output.metrics?.story_metrics?.overall ?? 0
  const inputQuality = output.metrics?.input_quality ?? 'unknown'
  const hours = totalEstimateHours(output.tasks)

  const chips = [
    { label: 'Epics', value: output.epics.length },
    { label: 'Stories', value: output.stories.length },
    { label: 'Tasks', value: output.tasks.length },
    { label: 'Est. Hours', value: hours },
    { label: 'Quality', value: `${quality}%` },
    {
      label: 'Input Quality',
      value: inputQuality.charAt(0).toUpperCase() + inputQuality.slice(1),
      color: QUALITY_COLOR[inputQuality],
    },
  ]

  return (
    <div className={`${styles.grid} ${compact ? styles.compact : ''}`}>
      {chips.map((c) => (
        <div key={c.label} className={styles.chip}>
          <div className={styles.value} style={c.color ? { color: c.color } : undefined}>
            {c.value}
          </div>
          <div className={styles.label}>{c.label}</div>
        </div>
      ))}
    </div>
  )
}
