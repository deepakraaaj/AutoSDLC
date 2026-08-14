import { useMemo, useState } from 'react'
import type { Epic, GenerationOutput, Hierarchy, Story, Task } from '../../types'
import { hierarchyIsPopulated, hierarchyToTree, outputToTree, type TreeEpic, type TreeStory, type TreeTask } from '../../lib/tree'
import { deriveEpicProgress, deriveEpicsPhaseStatus, type PhaseStatus } from '../../lib/epicProgress'
import type { DetailTarget } from './DetailModal'
import { ChangeRequestChat } from './ChangeRequestChat'
import styles from './WorkflowVisualizer.module.css'

const ICON: Record<PhaseStatus, string> = { pending: '', active: '', done: '✓' }

type ItemPhase = 'stories' | 'tasks' | 'tests'

interface Row {
  key: string
  title: string
  storyCount: number
  taskCount: number
  testCount: number
  storiesStatus: PhaseStatus
  tasksStatus: PhaseStatus
  testsStatus: PhaseStatus
  /** Present once this epic is DB-backed (has a dbId) — that's what makes
   * it (and everything under it) editable via DetailModal. Live/SSE rows
   * during an in-flight phase have nothing to persist against yet, same
   * rule DetailModal itself already enforces (canEdit = dbId != null). */
  epic: TreeEpic | null
}

/**
 * Admin-only "interrupt and change anything" view: one card per epic
 * showing where each phase (epics/stories/tasks/tests) actually stands,
 * with every item underneath clickable straight into the same editable
 * DetailModal the rest of the app uses (Stage 3).
 *
 * Two data sources, not one, because "during" and "after" a generation are
 * genuinely different shapes:
 *  - While generating, the only thing that updates live is the flat
 *    liveEpics/liveStories/liveTasks SSE arrays — reused via the existing
 *    deriveEpicProgress (same function EpicProgressMap already uses for the
 *    non-admin live view). Nothing in this branch has a dbId yet, so rows
 *    are informational only — consistent with the dbId-gated editing rule
 *    everywhere else in this app.
 *  - Once nothing is streaming (freshly finished, paused between
 *    step-by-step phases, or loaded from history), status is computed
 *    directly off the same TreeEpic[] OutputView already builds
 *    (hierarchyToTree when persisted, outputToTree as a pre-persist
 *    fallback) rather than forced back through deriveEpicProgress — its
 *    "started but not done yet" heuristic exists specifically to cover
 *    out-of-order concurrent SSE arrival, which doesn't apply once nothing
 *    is actually running.
 */
export function WorkflowVisualizer({
  liveEpics,
  liveStories,
  liveTasks,
  hierarchy,
  output,
  genId,
  isGenerating,
  onOpenDetail,
  onChanged,
}: {
  liveEpics: Epic[]
  liveStories: Story[]
  liveTasks: Task[]
  hierarchy: Hierarchy | null
  output: GenerationOutput | null
  /** Threaded through to ChangeRequestChat — /assistant/chat resolves a change_request's
   * target against this generation's saved hierarchy, so nothing can be confirmed without it. */
  genId: number | null
  isGenerating: boolean
  onOpenDetail: (target: DetailTarget) => void
  /** Called after a change_request is confirmed, same as DetailModal's onSaved — the parent
   * refreshes the hierarchy so the cards here (and everywhere else) reflect the edit. */
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState<{ epicKey: string; phase: ItemPhase } | null>(null)

  const rows = useMemo<Row[]>(() => {
    if (isGenerating) {
      return deriveEpicProgress(liveEpics, liveStories, liveTasks).map((r) => ({
        key: r.epic.id,
        title: r.epic.title,
        storyCount: r.storyCount,
        taskCount: r.taskCount,
        testCount: r.testCount,
        storiesStatus: r.storiesStatus,
        tasksStatus: r.tasksStatus,
        testsStatus: r.testsStatus,
        epic: null,
      }))
    }
    const tree = hierarchyIsPopulated(hierarchy) ? hierarchyToTree(hierarchy!) : output ? outputToTree(output) : []
    return tree.map((epic) => {
      const taskCount = epic.stories.reduce((n, s) => n + s.tasks.length, 0)
      const testCount = epic.stories.reduce((n, s) => n + s.tasks.reduce((m, t) => m + t.testCases.length, 0), 0)
      return {
        key: epic.key,
        title: epic.title,
        storyCount: epic.stories.length,
        taskCount,
        testCount,
        storiesStatus: epic.stories.length > 0 ? 'done' : 'pending',
        tasksStatus: epic.stories.length === 0 ? 'pending' : taskCount > 0 ? 'done' : 'pending',
        testsStatus: taskCount === 0 ? 'pending' : testCount > 0 ? 'done' : 'pending',
        epic,
      }
    })
  }, [isGenerating, liveEpics, liveStories, liveTasks, hierarchy, output])

  const epicCount = isGenerating ? liveEpics.length : rows.length
  const epicsStatus = deriveEpicsPhaseStatus(epicCount, isGenerating)

  if (epicCount === 0) return null

  return (
    <div className={styles.wrap}>
      <button type="button" className={styles.toggle} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className={styles.toggleIcon}>{open ? '▾' : '▸'}</span>
        Workflow visualizer
        <PhaseChip label="Epics" status={epicsStatus} count={epicCount} />
        <span className={styles.hint}>{open ? '' : 'click any item to edit it directly'}</span>
      </button>

      {open && (
        <div className={styles.grid}>
          {rows.map((row) => (
            <div
              key={row.key}
              className={`${styles.card} ${row.storiesStatus === 'active' || row.tasksStatus === 'active' || row.testsStatus === 'active' ? styles.cardActive : ''}`}
            >
              {row.epic ? (
                <button
                  type="button"
                  className={styles.epicTitle}
                  title={row.title}
                  onClick={() => onOpenDetail({ kind: 'epic', epic: row.epic! })}
                >
                  {row.title}
                </button>
              ) : (
                <div className={styles.epicTitleStatic} title={row.title}>
                  {row.title}
                </div>
              )}
              <div className={styles.phases}>
                <PhaseChip
                  label="Stories"
                  status={row.storiesStatus}
                  count={row.storyCount}
                  onClick={row.epic && row.storyCount ? () => setExpanded({ epicKey: row.key, phase: 'stories' }) : undefined}
                />
                <PhaseChip
                  label="Tasks"
                  status={row.tasksStatus}
                  count={row.taskCount}
                  onClick={row.epic && row.taskCount ? () => setExpanded({ epicKey: row.key, phase: 'tasks' }) : undefined}
                />
                <PhaseChip
                  label="Tests"
                  status={row.testsStatus}
                  count={row.testCount}
                  onClick={row.epic && row.testCount ? () => setExpanded({ epicKey: row.key, phase: 'tests' }) : undefined}
                />
              </div>
              {row.epic && expanded?.epicKey === row.key && (
                <ItemList epic={row.epic} phase={expanded.phase} onOpenDetail={onOpenDetail} onCollapse={() => setExpanded(null)} />
              )}
            </div>
          ))}
        </div>
      )}

      {open && <ChangeRequestChat genId={genId} onChanged={onChanged} />}
    </div>
  )
}

function PhaseChip({ label, status, count, onClick }: { label: string; status: PhaseStatus; count: number; onClick?: () => void }) {
  const className = `${styles.chip} ${styles[status]} ${onClick ? styles.clickable : ''}`
  const content = (
    <>
      <span className={styles.chipIcon} aria-hidden="true">
        {status === 'active' ? <span className={styles.spinner} /> : ICON[status]}
      </span>
      <span className={styles.chipLabel}>{label}</span>
      {count > 0 && <span className={styles.chipCount}>{count}</span>}
    </>
  )
  if (onClick) {
    return (
      <button type="button" className={className} onClick={onClick} title={`View ${label.toLowerCase()}`}>
        {content}
      </button>
    )
  }
  return <div className={className}>{content}</div>
}

function ItemList({
  epic,
  phase,
  onOpenDetail,
  onCollapse,
}: {
  epic: TreeEpic
  phase: ItemPhase
  onOpenDetail: (target: DetailTarget) => void
  onCollapse: () => void
}) {
  const items: { key: string; title: string; onClick: () => void }[] =
    phase === 'stories'
      ? epic.stories.map((story: TreeStory) => ({
          key: story.key,
          title: `${story.id}: ${story.title}`,
          onClick: () => onOpenDetail({ kind: 'story', epic, story }),
        }))
      : phase === 'tasks'
        ? epic.stories.flatMap((story: TreeStory) =>
            story.tasks.map((task: TreeTask) => ({
              key: task.key,
              title: `${task.id}: ${task.title}`,
              onClick: () => onOpenDetail({ kind: 'task', epic, story, task }),
            })),
          )
        : epic.stories.flatMap((story: TreeStory) =>
            story.tasks.flatMap((task: TreeTask) =>
              task.testCases.map((test) => ({
                key: `${task.key}-${test.id}`,
                title: `${test.id}: ${test.title}`,
                onClick: () => onOpenDetail({ kind: 'task', epic, story, task }),
              })),
            ),
          )

  return (
    <div className={styles.itemList}>
      {items.map((item) => (
        <button key={item.key} type="button" className={styles.item} onClick={item.onClick}>
          {item.title}
        </button>
      ))}
      <button type="button" className={styles.collapseBtn} onClick={onCollapse}>
        Collapse
      </button>
    </div>
  )
}
