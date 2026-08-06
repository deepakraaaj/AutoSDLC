import type { TreeEpic, TreeStory } from '../../lib/tree'
import type { DetailTarget } from './DetailModal'
import { PriorityBadge, PrioritySourceNote } from './PriorityBadge'
import { StatusBadge, StaticStatusBadge } from './StatusBadge'
import { TaskRow } from './TaskRow'
import styles from './HierarchyTree.module.css'

const STORY_STATUS_OPTIONS = ['planned', 'in-progress', 'review', 'done']

export function StoryRow({
  epic,
  story,
  open,
  onToggle,
  openTaskKeys,
  onToggleTask,
  onStoryStatusChange,
  onTaskStatusChange,
  onAssigneeChange,
  onOpenDetail,
}: {
  epic: TreeEpic
  story: TreeStory
  open: boolean
  onToggle: () => void
  openTaskKeys: Set<string>
  onToggleTask: (key: string) => void
  onStoryStatusChange: (dbId: number, status: string) => void
  onTaskStatusChange: (dbId: number, status: string) => void
  onAssigneeChange: (dbId: number, value: string) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  return (
    <div className={styles.storyCard}>
      <div
        className={styles.storyHeader}
        onClick={() => onOpenDetail({ kind: 'story', epic, story })}
        role="button"
        tabIndex={0}
        title="Open story details"
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onOpenDetail({ kind: 'story', epic, story })
          }
        }}
      >
        <span
          className={styles.chevron}
          title={open ? 'Collapse story' : 'Expand story'}
          onClick={(e) => {
            e.stopPropagation()
            onToggle()
          }}
        >
          {open ? '▾' : '▸'}
        </span>
        <span className={styles.idLabel}>{story.id}</span>
        <span
          className={`${styles.rowTitle} ${styles.rowTitleClickable}`}
        >
          {story.title}
        </span>
        <PriorityBadge priority={story.priority} redmineName={story.redminePriorityName} />
        <PrioritySourceNote priority={story.priority} redmineName={story.redminePriorityName} />
        {story.dbId != null ? (
          <StatusBadge
            status={story.status}
            options={STORY_STATUS_OPTIONS}
            onChange={(next) => onStoryStatusChange(story.dbId!, next)}
          />
        ) : (
          <StaticStatusBadge status={story.status} />
        )}
      </div>
      {open && (
        <div className={styles.storyBody}>
          <p className={styles.storyStatement}>
            <em>{story.asA}</em> → <strong>{story.iWant}</strong>
          </p>
          {story.tasks.map((task) => (
            <TaskRow
              key={task.key}
              epic={epic}
              story={story}
              task={task}
              open={openTaskKeys.has(task.key)}
              onToggle={() => onToggleTask(task.key)}
              onStatusChange={onTaskStatusChange}
              onAssigneeChange={onAssigneeChange}
              onOpenDetail={onOpenDetail}
            />
          ))}
        </div>
      )}
    </div>
  )
}
