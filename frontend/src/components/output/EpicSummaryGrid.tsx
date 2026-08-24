import type { TreeEpic } from '../../lib/tree'
import { priorityTone } from '../../lib/format'
import { StaticStatusBadge } from './StatusBadge'
import type { DetailTarget } from './DetailModal'
import styles from './EpicSummaryGrid.module.css'

/**
 * A scannable grid of epic cards — click one to open its detail modal. This is
 * what makes the Overview tab a real overview: not the same nested epic ->
 * story -> task tree the Hierarchy tab already shows (that stayed
 * indistinguishable from Hierarchy when both rendered HierarchyView), but a
 * flat, non-interactive-until-clicked summary of what's in this backlog.
 */
export function EpicSummaryGrid({ tree, onOpenDetail }: { tree: TreeEpic[]; onOpenDetail: (target: DetailTarget) => void }) {
  if (tree.length === 0) {
    return <p className={styles.empty}>No epics yet.</p>
  }

  return (
    <div className={styles.grid}>
      {tree.map((epic) => {
        const taskCount = epic.stories.reduce((n, s) => n + s.tasks.length, 0)
        const priorityDisplay = epic.redminePriorityName || epic.priority
        return (
          <button key={epic.key} type="button" className={styles.card} onClick={() => onOpenDetail({ kind: 'epic', epic })}>
            <div className={styles.top}>
              {epic.id && <span className={styles.idLabel}>{epic.id}</span>}
              <span className={styles.title}>{epic.title}</span>
            </div>
            {epic.description && <p className={styles.description}>{epic.description}</p>}
            <div className={styles.bottom}>
              <StaticStatusBadge status={epic.status} />
              {priorityDisplay && (
                <span className={`badge badge-priority badge-priority-${priorityTone(priorityDisplay)}`}>{priorityDisplay}</span>
              )}
              <span className={styles.counts}>
                {epic.stories.length} stories · {taskCount} tasks
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
