import { useEffect, useState } from 'react'
import type { GenStep } from '../hooks/useGeneration'
import { formatDuration } from '../lib/format'
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
  startedAt,
  estimatedSeconds,
}: {
  step: GenStep
  message: string
  counts: { epics: number; stories: number; tasks: number }
  onStop: () => void
  /** Client timestamp (Date.now()) generation started — drives the live
   * elapsed timer below. Absent (e.g. loaded from history) skips the timer. */
  startedAt?: number | null
  /** Pre-generation estimate from /estimate-tokens, shown next to the live
   * elapsed count so there's something to compare progress against. */
  estimatedSeconds?: number | null
}) {
  const activeIndex = STEPS.findIndex((s) => s.id === step)
  const hasCounts = counts.epics > 0 || counts.stories > 0 || counts.tasks > 0

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!startedAt || step === 'done') return
    setNow(Date.now())
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [startedAt, step])
  const elapsedSeconds = startedAt ? Math.max(0, (now - startedAt) / 1000) : null

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
      {elapsedSeconds != null && (
        <div className={styles.timer}>
          Elapsed: <strong>{formatDuration(elapsedSeconds)}</strong>
          {estimatedSeconds != null && <> · Est. total ~{formatDuration(estimatedSeconds)}</>}
        </div>
      )}
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
