import type { ValidationResult } from '../../types'
import styles from './ValidationChecklist.module.css'

export function ValidationChecklist({ validation }: { validation: ValidationResult }) {
  return (
    <div className={`card ${styles.card}`}>
      <div className={styles.header}>Checks</div>
      <div className={styles.list}>
        {validation.checks.map((check) => (
          <div key={check.label} className={`${styles.row} ${check.passed ? styles.passed : styles.failed}`}>
            <div className={styles.icon}>{check.passed ? '✓' : '✗'}</div>
            <div className={styles.content}>
              <div className={styles.label}>{check.label}</div>
              <div className={styles.details}>
                <span className={styles.value}>{check.value}</span>
                <span className={styles.threshold}>({check.threshold})</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
