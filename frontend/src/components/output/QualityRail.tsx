import { useState } from 'react'
import type { GenerationOutput } from '../../types'
import type { WeakItem, ImproveQualityResult, QualityItemSelection, ImproveQualityProgress } from '../../api/client'
import { TrustBanner } from './TrustBanner'
import { ValidationChecklist } from './ValidationChecklist'
import { Scorecard } from './Scorecard'
import { GapsList } from './GapsList'
import styles from './QualityRail.module.css'

/**
 * The review context — trust level, checks, scores, gaps — as a rail beside the
 * backlog instead of four full-width panels stacked above it.
 *
 * The four components inside are used exactly as they were; only their container
 * changed. Below 1180px the rail cannot hold a column of its own, so it becomes a
 * sheet driven by `sheetOpen` from the header's Quality button.
 */
export function QualityRail({
  output,
  sheetOpen,
  onCloseSheet,
  collapsed = false,
  onCollapseRail,
  onExpandRail,
  onCopy,
  onRepairDependencies,
  repairingDependencies,
  onAnalyzeWeakItems,
  onFixWeakItems,
  boostingQuality,
  fixProgress,
}: {
  output: GenerationOutput
  sheetOpen: boolean
  onCloseSheet: () => void
  /** Desktop-only: hides the persistent rail without touching the mobile sheet. */
  collapsed?: boolean
  /** Fully hides the desktop rail (reclaims its column) — previously only
   * reachable via OverviewMetaBar's panel-toggle icon, which only renders on
   * the Overview tab (showMeta={route.view === 'overview'} in App.tsx). The
   * rail itself renders on every backlog view, so Epics/Stories/Tasks/Tests/
   * Hierarchy had no way to dismiss it at all. This close button lives in
   * the rail's own header instead, so it works everywhere the rail does. */
  onCollapseRail?: () => void
  /** Reopens it — same reachability gap as onCollapseRail: without this
   * rendered on every view, closing from a non-Overview tab would strand
   * the user with no way back in short of navigating to Overview. */
  onExpandRail?: () => void
  onCopy: () => void
  onRepairDependencies: () => void
  repairingDependencies: boolean
  onAnalyzeWeakItems: (dimension?: string) => Promise<WeakItem[] | null>
  onFixWeakItems: (items: QualityItemSelection[]) => Promise<ImproveQualityResult | null>
  boostingQuality: boolean
  fixProgress: ImproveQualityProgress | null
}) {
  const [open, setOpen] = useState(true)

  if (!output.validation && !output.metrics && output.gaps.length === 0) return null

  const dependenciesWeak = Boolean(output.metrics && output.metrics.task_metrics.dependency_score < 70)
  // Collapsing is a wide-layout affordance: its toggle is hidden in sheet mode, so a
  // rail left collapsed on desktop must not open empty on a phone.
  const expanded = open || sheetOpen

  const rail = (
    <aside
      className={`${styles.rail} ${sheetOpen ? styles.sheet : ''} ${collapsed ? styles.railCollapsed : ''}`}
      aria-label="Quality"
    >
      <div className={styles.sheetHead}>
        <span className={styles.sheetTitle}>Quality</span>
        <button type="button" className={styles.sheetClose} onClick={onCloseSheet} aria-label="Close quality panel">
          ✕
        </button>
      </div>

      <div className={styles.headRow}>
        <button type="button" className={styles.head} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          Quality
          <svg
            className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden="true"
          >
            <path d="M2.5 4.5 6 8l3.5-3.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {/* Distinct from the chevron above: that only collapses this section's
            own body (the "Quality" strip stays put). This dismisses the whole
            rail and gives its column back to the backlog — the only other way
            to do that is OverviewMetaBar's icon, which doesn't exist outside
            the Overview tab. */}
        {onCollapseRail && (
          <button type="button" className={styles.railClose} onClick={onCollapseRail} aria-label="Hide quality panel" title="Hide quality panel">
            ✕
          </button>
        )}
      </div>

      {expanded && (
        <div className={styles.body}>
          {output.validation && (
            <TrustBanner
              validation={output.validation}
              actionLabel={dependenciesWeak ? 'Fix task dependencies' : undefined}
              onAction={dependenciesWeak ? onRepairDependencies : undefined}
              actionBusy={repairingDependencies}
            />
          )}
          {output.validation && <ValidationChecklist validation={output.validation} />}
          {output.metrics && (
            <Scorecard
              metrics={output.metrics}
              onCopy={onCopy}
              onAnalyzeWeakItems={onAnalyzeWeakItems}
              onFixWeakItems={onFixWeakItems}
              boostingQuality={boostingQuality}
              fixProgress={fixProgress}
            />
          )}
          <GapsList gaps={output.gaps} />
        </div>
      )}
    </aside>
  )

  return (
    <>
      {sheetOpen && <div className={styles.scrim} onClick={onCloseSheet} />}
      {/* Collapsing removes the rail via CSS (.railCollapsed { display: none })
          rather than unmounting it, so it isn't in the accessibility tree or
          tab order while hidden — this tab is the only visible trace of it,
          and the only way back in on any view but Overview. */}
      {collapsed && !sheetOpen && onExpandRail && (
        <button type="button" className={styles.reopenTab} onClick={onExpandRail} aria-label="Show quality panel" title="Show quality panel">
          Quality
        </button>
      )}
      {rail}
    </>
  )
}
