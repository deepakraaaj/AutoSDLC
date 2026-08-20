import { useEffect, useState } from 'react'
import type { Phase } from '../../hooks/useGeneration'
import type { GenerationOutput, Hierarchy } from '../../types'
import { PhaseList, type PhaseListHandlers } from './PhaseList'
import { phaseContent, phaseHasContent, phaseCount } from '../../lib/phases'
import styles from './PhaseTabs.module.css'

const TABS: { id: Phase; label: string }[] = [
  { id: 'epics', label: 'Epics' },
  { id: 'stories', label: 'Stories' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'tests', label: 'Test Cases' },
]

/** What clicking "Generate" on a tab actually does — shown before the user
 * spends an AI call finding out, not after. */
const PHASE_DESCRIPTIONS: Record<Phase, string> = {
  epics: 'Extracts feature areas and epics from your brief.',
  stories: 'Generates only the user stories supported by each epic, with acceptance criteria.',
  tasks: 'Breaks each story into the implementation tasks it actually needs.',
  tests: 'Generates manual test cases for every task.',
}

/** The step-by-step generation checkpoint: one tab per phase, sequentially gated,
 * with the "Generate <next phase>" CTA. Only for a run that's paused mid-way —
 * `awaitingPhase` names the phase waiting to run.
 *
 * A *finished* run isn't shown through this at all; it gets the routed
 * /app/backlog/:genId/:view pages (see lib/route.ts), which render the same
 * PhaseList content one addressable page at a time.
 *
 * App.tsx gates this out while a phase is actively generating, so ProgressPanel
 * stays the single "something is happening" indicator instead of the two overlapping. */
export function PhaseTabs({
  awaitingPhase,
  output,
  hierarchy,
  onGenerateNext,
  isGenerating,
  handlers,
}: {
  awaitingPhase: Phase
  output: GenerationOutput
  hierarchy: Hierarchy | null
  onGenerateNext: () => void
  isGenerating: boolean
  handlers: PhaseListHandlers
}) {
  const content = phaseContent(output, hierarchy)
  const hasContent = phaseHasContent(content)

  const frontierIndex = TABS.findIndex((t) => t.id === awaitingPhase)
  const previousPhaseLabel = TABS[Math.max(0, frontierIndex - 1)]?.label ?? 'Backlog'
  const nextPhaseLabel = TABS[frontierIndex]?.label ?? 'next phase'
  // The awaiting phase has no content yet. Start on the most recently
  // completed phase so a successful generation never lands on a blank tab.
  // The user can still open the frontier tab to read what the next call does.
  const latestCompletedPhase = TABS[Math.max(0, frontierIndex - 1)]?.id ?? 'epics'
  const [active, setActive] = useState<Phase>(latestCompletedPhase)

  // Keep this navigation mounted throughout generation. When a phase
  // completes, advance its content to the result that just became available.
  useEffect(() => {
    setActive(latestCompletedPhase)
  }, [latestCompletedPhase])

  return (
    <div className={`card ${styles.box}`}>
      <div className={styles.stickyHeader}>
        <div className={styles.checkpointHeader}>
          <div>
            <p className={styles.eyebrow}>Backlog checkpoint</p>
            <h2>{previousPhaseLabel} are ready. Generate {nextPhaseLabel.toLowerCase()} next.</h2>
            <p>Review the {previousPhaseLabel.toLowerCase()} below, then continue when you’re happy with them.</p>
          </div>
          <button className="btn btn-primary" onClick={onGenerateNext} disabled={isGenerating}>
            {isGenerating ? `Generating ${nextPhaseLabel}…` : `Generate ${nextPhaseLabel}`}
          </button>
        </div>
        <div className={styles.tabBar} role="tablist" aria-label="Generation phase">
          {TABS.map((t, i) => {
            const unlocked = i <= frontierIndex
            return (
              <button
                key={t.id}
                role="tab"
                aria-selected={active === t.id}
                disabled={!unlocked}
                className={`${styles.tab} ${active === t.id ? styles.tabActive : ''} ${i < frontierIndex ? styles.tabDone : ''}`}
                onClick={() => unlocked && setActive(t.id)}
                title={unlocked ? undefined : `Generate ${TABS[i - 1]?.label ?? 'the previous phase'} first`}
              >
                {t.label}
                {hasContent[t.id] && <span className={styles.tabCount}>{phaseCount(content, t.id)}</span>}
              </button>
            )
          })}
        </div>
      </div>

      <div className={styles.panel}>
        {active === awaitingPhase && (
          <div className={styles.generateRow}>
            <p className={styles.description}>{PHASE_DESCRIPTIONS[awaitingPhase]}</p>
          </div>
        )}
        <PhaseList phase={active} content={content} handlers={handlers} />
      </div>
    </div>
  )
}
