import { useEffect, useRef } from 'react'
import type { GenerationOutput, Hierarchy, Priority } from '../../types'
import { hierarchyIsPopulated, hierarchyToTree, outputToTree } from '../../lib/tree'
import { HierarchyView } from './HierarchyView'
import { EpicSummaryGrid } from './EpicSummaryGrid'
import { OverviewMetaBar } from './OverviewMetaBar'
import { OverviewWikiPanel } from './OverviewWikiPanel'
import type { DetailTarget } from './DetailModal'
import styles from './OutputView.module.css'

/**
 * The backlog itself. Trust, checks, scores and gaps used to be stacked above this
 * as four full-width panels; they now live in QualityRail beside it, so the page
 * opens on the thing it is named after.
 *
 * `showMeta` doubles as "which page is this" — true only for Overview. Overview
 * and Hierarchy used to render this exact same component with no distinction at
 * all (a leftover from moving Quality into the rail), so Overview's card was
 * labeled "Hierarchy" and showed the identical nested tree one click away on the
 * Hierarchy tab — indistinguishable, confusing, pointless as two tabs. Overview
 * now gets its own content: a flat, scannable grid of epic cards (EpicSummaryGrid)
 * instead of the full interactive epic->story->task tree, which stays exactly as
 * it was on Hierarchy.
 */
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
  showMeta = false,
  railOpen = true,
  onToggleRail,
  onGenerateRemaining,
  hierarchyFocusStoryId = null,
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
  /** True on Overview only — also decides which body renders (see above). */
  showMeta?: boolean
  railOpen?: boolean
  onToggleRail?: () => void
  onGenerateRemaining?: () => void
  hierarchyFocusStoryId?: string | null
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const seenGenerationRef = useRef<number | null>(null)

  // Scroll to the top of the backlog when a *different* generation arrives — not on
  // every change to `output`. Editing a status refreshes the hierarchy, which used to
  // yank the page back up mid-review.
  useEffect(() => {
    const id = output.generation_id ?? null
    if (seenGenerationRef.current === id) return
    seenGenerationRef.current = id
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

  return (
    <div ref={rootRef} className={styles.section}>
      {showMeta && onToggleRail && (
        <OverviewMetaBar output={output} railOpen={railOpen} onToggleRail={onToggleRail} />
      )}
      {showMeta && output.tasks.length === 0 && onGenerateRemaining && (
        <div
          className="card"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-4)',
            marginBottom: 'var(--space-4)',
            background: 'var(--accent-subtle)',
            borderColor: 'var(--accent-border)',
          }}
        >
          <div>
            <strong style={{ color: 'var(--accent)' }}>Tasks & Test Cases not generated yet</strong>
            <p className="field-hint" style={{ margin: '2px 0 0' }}>
              This backlog currently contains epics and stories. Generate the implementation tasks and test cases now.
            </p>
          </div>
          <button className="btn btn-primary btn-sm" onClick={onGenerateRemaining} style={{ flexShrink: 0 }}>
            Generate Tasks & Tests
          </button>
        </div>
      )}
      {showMeta && output.project_id != null && <OverviewWikiPanel projectId={output.project_id} />}
      <div className={styles.hierarchyWorkspace}>
        <div className={styles.sectionHeader}>
          <div>
            <div className={styles.headingRow}>
              <h2>{showMeta ? 'Epics' : 'Hierarchy'}</h2>
              <span className={styles.countPill}>{hierarchyTotals.epics} epics</span>
              <span className={styles.countText}>
                {hierarchyTotals.stories} stories · {hierarchyTotals.tasks} tasks
              </span>
            </div>
          </div>
          {hierarchyIsPopulated(hierarchy) && (
            <button className="btn btn-secondary" onClick={onCreateEpic}>
              Add epic
            </button>
          )}
        </div>
        {showMeta ? (
          <EpicSummaryGrid tree={tree} onOpenDetail={onOpenDetail} />
        ) : (
          <HierarchyView
            tree={tree}
            focusStoryId={hierarchyFocusStoryId}
            onEpicStatusChange={onEpicStatusChange}
            onStoryStatusChange={onStoryStatusChange}
            onTaskStatusChange={onTaskStatusChange}
            onEpicPriorityChange={onEpicPriorityChange}
            onStoryPriorityChange={onStoryPriorityChange}
            onTaskPriorityChange={onTaskPriorityChange}
            onAssigneeChange={onAssigneeChange}
            onOpenDetail={onOpenDetail}
          />
        )}
      </div>
    </div>
  )
}
