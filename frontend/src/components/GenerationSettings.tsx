import styles from './GenerationSettings.module.css'
import { DENIED_MESSAGES } from '../lib/roles'
import { useRole } from '../hooks/useRole'

export type GenerationMode = 'auto' | 'stepwise'

export interface QualitySettings {
  clarifyFirst: boolean
  instructions: string
  /** 'auto' (default) runs Epics -> Stories -> Tasks -> Test Cases straight
   * through, same as always. 'stepwise' pauses after each phase so the user
   * can review before clicking to continue — see useGeneration's runPhase. */
  generationMode: GenerationMode
}

export const DEFAULT_QUALITY_INSTRUCTIONS =
  'Prioritize completeness, correctness, traceability, testable acceptance criteria, measurable definitions of done, edge cases, security, and failure handling. Do not invent missing business facts; record unresolved assumptions as gaps.'

export function GenerationSettings({
  value,
  onChange,
}: {
  value: QualitySettings
  onChange: (value: QualitySettings) => void
}) {
  const { canUseOneClickGeneration: canOneClick } = useRole()
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

      <label className="field-label" htmlFor="generation-mode">Generation flow</label>
      <select
        id="generation-mode"
        className="select"
        value={value.generationMode}
        onChange={(e) => onChange({ ...value, generationMode: e.target.value as GenerationMode })}
      >
        {canOneClick && <option value="auto">Generate everything at once</option>}
        <option value="stepwise">Step through each phase (Epics → Stories → Tasks → Test Cases)</option>
      </select>
      {!canOneClick && <p className="field-hint">{DENIED_MESSAGES.oneClickGeneration}</p>}
    </details>
  )
}
