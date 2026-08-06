import styles from './GenerationSettings.module.css'

export interface QualitySettings {
  clarifyFirst: boolean
  instructions: string
}

export const DEFAULT_QUALITY_INSTRUCTIONS =
  'Prioritize completeness, correctness, traceability, testable acceptance criteria, measurable definitions of done, edge cases, security, and failure handling. Do not invent missing business facts; record unresolved assumptions as gaps.'

export function GenerationSettings({ value, onChange }: { value: QualitySettings; onChange: (value: QualitySettings) => void }) {
  return (
    <details className={`card ${styles.panel}`}>
      <summary>Quality & Context settings <span>Quality-first · No item limits</span></summary>
      <label className={styles.toggle}>
        <input type="checkbox" checked={value.clarifyFirst} onChange={(e) => onChange({ ...value, clarifyFirst: e.target.checked })} />
        Ask focused clarification questions when context is insufficient
      </label>
      <label className="field-label" htmlFor="quality-instructions">Default quality prompt</label>
      <textarea id="quality-instructions" className="textarea" rows={4} value={value.instructions} onChange={(e) => onChange({ ...value, instructions: e.target.value })} />
      <p className="field-hint">These instructions guide quality only; they do not cap epics, stories, or tasks.</p>
    </details>
  )
}
