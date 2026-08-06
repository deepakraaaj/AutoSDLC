import type { ValidationResult } from '../../types'
import styles from './TrustBanner.module.css'

const LEVEL_TEXT: Record<string, string> = {
  trusted: 'TRUSTED OUTPUT',
  review: 'REVIEW NEEDED',
  low: 'LOW CONFIDENCE',
}
const ICON: Record<string, string> = { trusted: '✓', review: '!', low: '✕' }

export function TrustBanner({ validation }: { validation: ValidationResult }) {
  const passedCount = validation.checks.filter((c) => c.passed).length
  return (
    <div className={`${styles.banner} ${styles[validation.trust_level]}`}>
      <div className={styles.icon}>{ICON[validation.trust_level] ?? '?'}</div>
      <div className={styles.body}>
        <div className={styles.level}>{LEVEL_TEXT[validation.trust_level] ?? validation.trust_level}</div>
        <div className={styles.recommendation}>{validation.recommendation}</div>
      </div>
      <div className={styles.badge}>
        {passedCount}/{validation.checks.length} checks passed
      </div>
    </div>
  )
}
