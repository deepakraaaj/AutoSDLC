import type { ValidationResult } from '../../types'
import styles from './TrustBanner.module.css'

const LEVEL_TEXT: Record<string, string> = {
  trusted: 'TRUSTED OUTPUT',
  review: 'REVIEW NEEDED',
  low: 'LOW CONFIDENCE',
}
const ICON: Record<string, string> = { trusted: '✓', review: '!', low: '✕' }

export function TrustBanner({
  validation,
  actionLabel,
  onAction,
  actionBusy = false,
}: {
  validation: ValidationResult
  actionLabel?: string
  onAction?: () => void
  actionBusy?: boolean
}) {
  const passedCount = validation.checks.filter((c) => c.passed).length
  return (
    <div className={`${styles.banner} ${styles[validation.trust_level]}`}>
      {/* Icon, level and the pass count share one row — they're all short, fixed-width
          pieces. The recommendation is prose and gets its own full-width line below,
          so it wraps normally instead of being squeezed into a narrow last column
          (one word per line) the way a single flex row forced it to at rail width. */}
      <div className={styles.headRow}>
        <div className={styles.icon}>{ICON[validation.trust_level] ?? '?'}</div>
        <div className={styles.level}>{LEVEL_TEXT[validation.trust_level] ?? validation.trust_level}</div>
        <div className={styles.badge}>
          {passedCount}/{validation.checks.length} checks
        </div>
      </div>
      <p className={styles.recommendation}>{validation.recommendation}</p>
      {actionLabel && onAction && (
        <button className="btn btn-secondary btn-sm btn-block" onClick={onAction} disabled={actionBusy}>
          {actionBusy ? 'Fixing…' : actionLabel}
        </button>
      )}
    </div>
  )
}
