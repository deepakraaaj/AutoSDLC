import type { Phase } from '../../hooks/useGeneration'
import type { Priority } from '../../types'
import type { TreeEpic, TreeStory } from '../../lib/tree'
import type { PhaseContent } from '../../lib/phases'
import { PriorityBadge, PrioritySourceNote } from './PriorityBadge'
import { StatusBadge, StaticStatusBadge } from './StatusBadge'
import { TestCasesPanel } from './TestCasesPanel'
import type { DetailTarget } from './DetailModal'
import hstyles from './HierarchyTree.module.css'
import styles from './PhaseTabs.module.css'

const EPIC_STATUS_OPTIONS = ['planned', 'in-progress', 'done']
const STORY_STATUS_OPTIONS = ['planned', 'in-progress', 'review', 'done']
const TASK_STATUS_OPTIONS = ['todo', 'in-progress', 'testing', 'done']

export interface PhaseListHandlers {
  onEpicStatusChange: (dbId: number, status: string) => void
  onStoryStatusChange: (dbId: number, status: string) => void
  onTaskStatusChange: (dbId: number, status: string) => void
  onEpicPriorityChange: (dbId: number, priority: Priority) => void
  onStoryPriorityChange: (dbId: number, priority: Priority) => void
  onTaskPriorityChange: (dbId: number, priority: Priority) => void
  onOpenDetail: (target: DetailTarget) => void
}

/** A flat list of just one phase — no nesting, which is the whole point of separating
 * the phases out. Uses the same badge/status controls (and HierarchyTree.module.css
 * classes) as the nested EpicRow/StoryRow/TaskRow tree. */
export function PhaseList({
  phase,
  content,
  handlers,
}: {
  phase: Phase
  content: PhaseContent
  handlers: PhaseListHandlers
}) {
  const { tree, stories, tasks } = content
  const {
    onEpicStatusChange, onStoryStatusChange, onTaskStatusChange,
    onEpicPriorityChange, onStoryPriorityChange, onTaskPriorityChange, onOpenDetail,
  } = handlers

  if (phase === 'epics') {
    return tree.length === 0 ? (
      <p className={styles.empty}>No epics yet.</p>
    ) : (
      <>
        {tree.map((epic) => (
          <EpicListItem
            key={epic.key}
            epic={epic}
            onStatusChange={onEpicStatusChange}
            onPriorityChange={onEpicPriorityChange}
            onOpenDetail={onOpenDetail}
          />
        ))}
      </>
    )
  }

  if (phase === 'stories') {
    return stories.length === 0 ? (
      <p className={styles.empty}>No stories yet.</p>
    ) : (
      <>
        {stories.map(({ epic, story }) => (
          <StoryListItem
            key={story.key}
            epic={epic}
            story={story}
            onStatusChange={onStoryStatusChange}
            onPriorityChange={onStoryPriorityChange}
            onOpenDetail={onOpenDetail}
          />
        ))}
      </>
    )
  }

  return tasks.length === 0 ? (
    <p className={styles.empty}>No tasks yet.</p>
  ) : (
    <>
      {tasks.map(({ epic, story, task }) => (
        <div key={task.key} className={hstyles.taskCard}>
          <div className={hstyles.taskHeader} onClick={() => onOpenDetail({ kind: 'task', epic, story, task })}>
            <span className={hstyles.idLabel}>{task.id}</span>
            <span className={`${hstyles.rowTitle} ${hstyles.rowTitleClickable}`}>{task.title}</span>
            <PriorityBadge
              priority={task.priority}
              redmineName={task.redminePriorityName}
              onChange={task.dbId != null ? (next) => onTaskPriorityChange(task.dbId!, next) : undefined}
            />
            <PrioritySourceNote priority={task.priority} redmineName={task.redminePriorityName} />
            {task.dbId != null ? (
              <StatusBadge status={task.status} options={TASK_STATUS_OPTIONS} onChange={(next) => onTaskStatusChange(task.dbId!, next)} />
            ) : (
              <StaticStatusBadge status={task.status} />
            )}
          </div>
          {phase === 'tests' && (
            <div className={hstyles.taskBody}>
              <TestCasesPanel testCases={task.testCases} />
            </div>
          )}
        </div>
      ))}
    </>
  )
}

function EpicListItem({
  epic,
  onStatusChange,
  onPriorityChange,
  onOpenDetail,
}: {
  epic: TreeEpic
  onStatusChange: (dbId: number, status: string) => void
  onPriorityChange: (dbId: number, priority: Priority) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  return (
    <div className={hstyles.epicCard}>
      <div className={hstyles.epicHeader} onClick={() => onOpenDetail({ kind: 'epic', epic })}>
        {epic.id && <span className={hstyles.idLabel}>{epic.id}</span>}
        <span className={`${hstyles.rowTitle} ${hstyles.rowTitleClickable}`}>{epic.title}</span>
        <PriorityBadge
          priority={epic.priority}
          redmineName={epic.redminePriorityName}
          onChange={epic.dbId != null ? (next) => onPriorityChange(epic.dbId!, next) : undefined}
        />
        <PrioritySourceNote priority={epic.priority} redmineName={epic.redminePriorityName} />
        {epic.dbId != null ? (
          <StatusBadge status={epic.status} options={EPIC_STATUS_OPTIONS} onChange={(next) => onStatusChange(epic.dbId!, next)} />
        ) : (
          <StaticStatusBadge status={epic.status} />
        )}
      </div>
      {epic.description && <p className={hstyles.epicDesc}>{epic.description}</p>}
    </div>
  )
}

function StoryListItem({
  epic,
  story,
  onStatusChange,
  onPriorityChange,
  onOpenDetail,
}: {
  epic: TreeEpic
  story: TreeStory
  onStatusChange: (dbId: number, status: string) => void
  onPriorityChange: (dbId: number, priority: Priority) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  return (
    <div className={hstyles.storyCard}>
      <div className={hstyles.storyHeader} onClick={() => onOpenDetail({ kind: 'story', epic, story })}>
        <span className={hstyles.idLabel}>{story.id}</span>
        <span className={`${hstyles.rowTitle} ${hstyles.rowTitleClickable}`}>{story.title}</span>
        <PriorityBadge
          priority={story.priority}
          redmineName={story.redminePriorityName}
          onChange={story.dbId != null ? (next) => onPriorityChange(story.dbId!, next) : undefined}
        />
        <PrioritySourceNote priority={story.priority} redmineName={story.redminePriorityName} />
        {story.dbId != null ? (
          <StatusBadge status={story.status} options={STORY_STATUS_OPTIONS} onChange={(next) => onStatusChange(story.dbId!, next)} />
        ) : (
          <StaticStatusBadge status={story.status} />
        )}
      </div>
      <p className={hstyles.storyStatement}>
        <em>{story.asA}</em> → <strong>{story.iWant}</strong>
      </p>
    </div>
  )
}
