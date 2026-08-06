import type { TreeEpic } from '../../lib/tree'
import type { DetailTarget } from './DetailModal'
import { PriorityBadge, PrioritySourceNote } from './PriorityBadge'
import { StatusBadge, StaticStatusBadge } from './StatusBadge'
import { StoryRow } from './StoryRow'
import styles from './HierarchyTree.module.css'

const EPIC_STATUS_OPTIONS = ['planned', 'in-progress', 'done']

export function EpicRow({
  epic,
  open,
  onToggle,
  closedStoryKeys,
  onToggleStory,
  openTaskKeys,
  onToggleTask,
  onEpicStatusChange,
  onStoryStatusChange,
  onTaskStatusChange,
  onAssigneeChange,
  onOpenDetail,
}: {
  epic: TreeEpic
  open: boolean
  onToggle: () => void
  closedStoryKeys: Set<string>
  onToggleStory: (key: string) => void
  openTaskKeys: Set<string>
  onToggleTask: (key: string) => void
  onEpicStatusChange: (dbId: number, status: string) => void
  onStoryStatusChange: (dbId: number, status: string) => void
  onTaskStatusChange: (dbId: number, status: string) => void
  onAssigneeChange: (dbId: number, value: string) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  return (
    <div className={styles.epicCard}>
      <div className={styles.epicHeader} onClick={onToggle}>
        <span className={styles.chevron}>{open ? '▾' : '▸'}</span>
        {epic.id && <span className={styles.idLabel}>{epic.id}</span>}
        <span
          className={`${styles.rowTitle} ${styles.rowTitleClickable}`}
          onClick={(e) => {
            e.stopPropagation()
            onOpenDetail({ kind: 'epic', epic })
          }}
        >
          {epic.title}
        </span>
        <PriorityBadge priority={epic.priority} redmineName={epic.redminePriorityName} />
        <PrioritySourceNote priority={epic.priority} redmineName={epic.redminePriorityName} />
        {epic.dbId != null ? (
          <StatusBadge
            status={epic.status}
            options={EPIC_STATUS_OPTIONS}
            onChange={(next) => onEpicStatusChange(epic.dbId!, next)}
          />
        ) : (
          <StaticStatusBadge status={epic.status} />
        )}
      </div>
      {open && (
        <div className={styles.epicBody}>
          {epic.description && <p className={styles.epicDesc}>{epic.description}</p>}
          {epic.stories.map((story) => (
            <StoryRow
              key={story.key}
              epic={epic}
              story={story}
              open={!closedStoryKeys.has(story.key)}
              onToggle={() => onToggleStory(story.key)}
              openTaskKeys={openTaskKeys}
              onToggleTask={onToggleTask}
              onStoryStatusChange={onStoryStatusChange}
              onTaskStatusChange={onTaskStatusChange}
              onAssigneeChange={onAssigneeChange}
              onOpenDetail={onOpenDetail}
            />
          ))}
        </div>
      )}
    </div>
  )
}
