import { useState } from 'react'
import type { TestCase } from '../../types'
import styles from './TestCasesPanel.module.css'

const TYPE_LABEL: Record<string, string> = {
  functional: 'Functional',
  edge_case: 'Edge case',
  negative: 'Negative',
  regression: 'Regression',
}

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
        <span>🧪</span> Test Cases ({testCases.length}) <span className={styles.chevron}>{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className={styles.list}>
          {testCases.map((tc, i) => (
            <div key={i} className={styles.item}>
              <div className={styles.title}>{tc.title}</div>
              <div className={styles.type}>{TYPE_LABEL[tc.test_type] ?? tc.test_type}</div>
              {tc.description && (
                <div className={styles.desc}>
                  <strong>What:</strong> {tc.description}
                </div>
              )}
              {tc.preconditions && tc.preconditions.toLowerCase() !== 'none' && (
                <div className={styles.desc}>
                  <strong>Preconditions:</strong> {tc.preconditions}
                </div>
              )}
              {tc.steps.length > 0 && (
                <div className={styles.steps}>
                  <strong>Steps:</strong>
                  <ol>
                    {tc.steps.map((step, si) => (
                      <li key={si}>{step}</li>
                    ))}
                  </ol>
                </div>
              )}
              {tc.expected_result && (
                <div className={styles.expected}>
                  <strong>Expected result:</strong> {tc.expected_result}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
