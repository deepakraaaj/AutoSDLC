import { useState } from 'react'
import type { TestCase } from '../../types'
import styles from './TestCasesPanel.module.css'

export function TestCasesPanel({ testCases }: { testCases: TestCase[] }) {
  const [open, setOpen] = useState(false)

  if (!testCases.length) {
    return (
      <div className={styles.section}>
        <div className={styles.empty}>ℹ️ No test cases generated</div>
      </div>
    )
  }

  return (
    <div className={styles.section}>
      <div
        className={styles.header}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
      >
        <span>🧪</span> Unit Tests ({testCases.length}) <span className={styles.chevron}>{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className={styles.list}>
          {testCases.map((tc, i) => (
            <div key={i} className={styles.item}>
              <div className={styles.title}>{tc.title}</div>
              <div className={styles.type}>{tc.test_type}</div>
              {tc.description && (
                <div className={styles.desc}>
                  <strong>What:</strong> {tc.description}
                </div>
              )}
              {tc.test_code && (
                <div className={styles.code}>
                  <strong>Code:</strong>
                  <br />
                  {tc.test_code}
                </div>
              )}
              {tc.assertion && (
                <div className={styles.assertion}>
                  <strong>Assert:</strong> {tc.assertion}
                </div>
              )}
              {tc.expected_result && (
                <div className={styles.desc}>
                  <strong>Expected:</strong> {tc.expected_result}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
