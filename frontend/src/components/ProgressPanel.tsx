import type { GenStep } from '../hooks/useGeneration'
import styles from './ProgressPanel.module.css'

const STEPS: { id: GenStep; label: string }[] = [
  { id: 'connecting', label: 'Connecting' },
  { id: 'generating', label: 'Generating' },
  { id: 'parsing', label: 'Parsing' },
  { id: 'scoring', label: 'Scoring' },
  { id: 'done', label: 'Done' },
]

export function ProgressPanel({
  step,
  message,
  counts,
  onStop,
}: {
  step: GenStep
  message: string
  counts: { epics: number; stories: number; tasks: number }
  onStop: () => void
}) {
  const activeIndex = STEPS.findIndex((s) => s.id === step)
  const hasCounts = counts.epics > 0 || counts.stories > 0 || counts.tasks > 0

  return (
    <div className={`card ${styles.box}`}>
      <div className={styles.steps}>
        {STEPS.map((s, i) => (
          <div key={s.id} className={styles.stepWrap}>
            <div
              className={`${styles.step} ${i < activeIndex ? styles.done : ''} ${i === activeIndex ? styles.active : ''}`}
            >
              <div className={styles.dot} />
              <span>{s.label}</span>
            </div>
            {i < STEPS.length - 1 && <div className={`${styles.line} ${i < activeIndex ? styles.lineDone : ''}`} />}
          </div>
        ))}
      </div>
      <div className={styles.label}>
        <span className={styles.pulse} />
        <span>{message}</span>
        {step !== 'done' && (
          <button className={`btn btn-secondary btn-sm ${styles.stopBtn}`} onClick={onStop}>
            Stop
          </button>
        )}
      </div>
      {hasCounts && (
        <div className={styles.counts}>
          {counts.epics} epic{counts.epics === 1 ? '' : 's'} · {counts.stories} stor
          {counts.stories === 1 ? 'y' : 'ies'} · {counts.tasks} task{counts.tasks === 1 ? '' : 's'} generated so far
          — building live below
        </div>
      )}
    </div>
  )
}
