import { useEffect, useRef } from 'react'
import type { GenerationOutput, Hierarchy, Priority } from '../../types'
import type { WeakItem, ImproveQualityResult, QualityItemSelection, ImproveQualityProgress } from '../../api/client'
import { hierarchyIsPopulated, hierarchyToTree, outputToTree } from '../../lib/tree'
import { copyText } from '../../lib/format'
import { useToast } from '../../hooks/useToast'
import { Dashboard } from './Dashboard'
import { TrustBanner } from './TrustBanner'
import { ValidationChecklist } from './ValidationChecklist'
import { Scorecard } from './Scorecard'
import { HierarchyView } from './HierarchyView'
import { GapsList } from './GapsList'
import type { DetailTarget } from './DetailModal'
import styles from './OutputView.module.css'

export function OutputView({
  output,
  hierarchy,
  onEpicStatusChange,
  onStoryStatusChange,
  onTaskStatusChange,
  onEpicPriorityChange,
  onStoryPriorityChange,
  onTaskPriorityChange,
  onAssigneeChange,
  onOpenDetail,
  onCreateEpic,
  onRepairDependencies,
  onAnalyzeWeakItems,
  onFixWeakItems,
  repairingDependencies = false,
  boostingQuality = false,
  fixProgress = null,
  showDashboard = true,
  section = 'all',
}: {
  output: GenerationOutput
  hierarchy: Hierarchy | null
  onEpicStatusChange: (dbId: number, status: string) => void
  onStoryStatusChange: (dbId: number, status: string) => void
  onTaskStatusChange: (dbId: number, status: string) => void
  onEpicPriorityChange: (dbId: number, priority: Priority) => void
  onStoryPriorityChange: (dbId: number, priority: Priority) => void
  onTaskPriorityChange: (dbId: number, priority: Priority) => void
  onAssigneeChange: (dbId: number, value: string) => void
  onOpenDetail: (target: DetailTarget) => void
  onCreateEpic: () => void
  onRepairDependencies: () => void
  onAnalyzeWeakItems: (dimension?: string) => Promise<WeakItem[] | null>
  onFixWeakItems: (items: QualityItemSelection[]) => Promise<ImproveQualityResult | null>
  repairingDependencies?: boolean
  boostingQuality?: boolean
  fixProgress?: ImproveQualityProgress | null
  showDashboard?: boolean
  /** Which part of the report to render. The backlog is split across addressable
   * pages (/app/backlog/:genId/overview vs /hierarchy) rather than stacking the
   * quality report and the whole tree into one very long page — 'all' keeps the
   * combined rendering for any caller that still wants it. */
  section?: 'all' | 'overview' | 'hierarchy'
}) {
  const { showToast } = useToast()
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [output])

  const tree = hierarchyIsPopulated(hierarchy) ? hierarchyToTree(hierarchy!) : outputToTree(output)
  const hierarchyTotals = tree.reduce(
    (totals, epic) => ({
      epics: totals.epics + 1,
      stories: totals.stories + epic.stories.length,
      tasks: totals.tasks + epic.stories.reduce((count, story) => count + story.tasks.length, 0),
    }),
    { epics: 0, stories: 0, tasks: 0 },
  )

  function copyOutput() {
    const lines: string[] = []
    output.stories.forEach((s) => {
      lines.push(`[${s.id}] ${s.title}`)
      lines.push(`As a ${s.as_a}, I want to ${s.i_want}, so that ${s.so_that}.`)
      s.acceptance_criteria.forEach((ac) => lines.push(`  ✓ ${ac}`))
      lines.push('')
    })
    output.tasks.forEach((t) => {
      lines.push(`[${t.id}] ${t.title} (${t.estimate_hours} hrs)`)
      lines.push(`  ${t.description}`)
      lines.push(`  Done: ${t.definition_of_done}`)
      lines.push('')
    })
    void copyText(lines.join('\n')).then(() => showToast('Copied', 'Backlog copied to clipboard.', 'info'))
  }

  const showOverview = section === 'all' || section === 'overview'
  const showHierarchy = section === 'all' || section === 'hierarchy'

  return (
    <div ref={rootRef}>
      {showDashboard && <Dashboard output={output} />}
      {showOverview && output.validation && (
        <TrustBanner
          validation={output.validation}
          actionLabel={output.metrics && output.metrics.task_metrics.dependency_score < 70 ? 'Fix task dependencies' : undefined}
          onAction={output.metrics && output.metrics.task_metrics.dependency_score < 70 ? onRepairDependencies : undefined}
          actionBusy={repairingDependencies}
        />
      )}
      {showOverview && (output.validation || output.metrics) && (
        <div className={styles.reviewGrid}>
          {output.validation && <ValidationChecklist validation={output.validation} />}
          {output.metrics && (
            <Scorecard
              metrics={output.metrics}
              onCopy={copyOutput}
              onAnalyzeWeakItems={onAnalyzeWeakItems}
              onFixWeakItems={onFixWeakItems}
              boostingQuality={boostingQuality}
              fixProgress={fixProgress}
            />
          )}
        </div>
      )}

      {showHierarchy && (
      <div className={styles.section}>
        <div className={styles.hierarchyWorkspace}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.sectionEyebrow}>Backlog workspace</p>
              <div className={styles.headingRow}>
                <h2>Hierarchy</h2>
                <span className={styles.countPill}>{hierarchyTotals.epics} epics</span>
                <span className={styles.countText}>{hierarchyTotals.stories} stories · {hierarchyTotals.tasks} tasks</span>
              </div>
              <p className={styles.sectionDescription}>Search, review, and update the delivery plan in one place.</p>
            </div>
            {hierarchyIsPopulated(hierarchy) && <button className="btn btn-primary" onClick={onCreateEpic}>Add epic</button>}
          </div>
          <HierarchyView
            tree={tree}
            onEpicStatusChange={onEpicStatusChange}
            onStoryStatusChange={onStoryStatusChange}
            onTaskStatusChange={onTaskStatusChange}
            onEpicPriorityChange={onEpicPriorityChange}
            onStoryPriorityChange={onStoryPriorityChange}
            onTaskPriorityChange={onTaskPriorityChange}
            onAssigneeChange={onAssigneeChange}
            onOpenDetail={onOpenDetail}
          />
        </div>
      </div>
      )}

      {showOverview && <GapsList gaps={output.gaps} />}
    </div>
  )
}
