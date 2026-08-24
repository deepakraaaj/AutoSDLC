import { useState } from 'react'
import type { TestCase } from '../../types'
import styles from './TestCasesPanel.module.css'

const TYPE_LABEL: Record<string, string> = {
  functional: 'Functional',
  edge_case: 'Edge case',
  negative: 'Negative',
  regression: 'Regression',
}

/** Generations saved before the TestCase redesign (test_code/assertion,
 * dropped in favor of preconditions/steps — see TestCase's docstring in
 * app/schemas/models.py) still have their old shape sitting in the
 * database untouched; there's no migration that rewrites saved rows. This
 * type covers the pre-redesign fields loosely so old data renders instead
 * of crashing the whole page — `tc.steps.length` on an old record where
 * `steps` doesn't exist is exactly what caused the white screen this fixes. */
type LegacyTestCase = { test_code?: string; assertion?: string }

function StepsOrLegacyCode({ tc }: { tc: TestCase & LegacyTestCase }) {
  const steps = tc.steps ?? []
  if (steps.length > 0) {
    return (
      <div className={styles.steps}>
        <strong>Steps:</strong>
        <ol>
          {steps.map((step, si) => (
            <li key={si}>{step}</li>
          ))}
        </ol>
      </div>
    )
  }
  // Pre-redesign record with no steps — show its old code snippet rather
  // than silently dropping the only content it has.
  if (tc.test_code) {
    return (
      <div className={styles.steps}>
        <strong>Test code</strong> <em>(saved before this became a manual test case)</em>
        <pre className={styles.legacyCode}>{tc.test_code}</pre>
      </div>
    )
  }
  return null
}

export function TestCasesPanel({ testCases }: { testCases: TestCase[] }) {
  const [open, setOpen] = useState(false)

  if (!testCases.length) {
    return (
      <div className={styles.section}>
        <div className={styles.empty}>No test cases generated</div>
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
          {testCases.map((tc, i) => {
            const legacy = tc as TestCase & LegacyTestCase
            return (
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
                <StepsOrLegacyCode tc={legacy} />
                {tc.expected_result && (
                  <div className={styles.expected}>
                    <strong>Expected result:</strong> {tc.expected_result}
                  </div>
                )}
                {legacy.assertion && (
                  <div className={styles.desc}>
                    <strong>Assertion</strong> <em>(legacy field):</em> {legacy.assertion}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
