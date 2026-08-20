import { useState } from 'react'
import type { TreeEpic, TreeStory, TreeTask } from '../../lib/tree'
import type { Priority } from '../../types'
import type { DetailTarget } from './DetailModal'
import { PriorityBadge, PrioritySourceNote } from './PriorityBadge'
import { StatusBadge, StaticStatusBadge } from './StatusBadge'
import { TestCasesPanel } from './TestCasesPanel'
import styles from './HierarchyTree.module.css'

const TASK_STATUS_OPTIONS = ['todo', 'in-progress', 'testing', 'done']

function formatEstimate(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  return /\b(hours?|hrs?)\b/i.test(trimmed) ? trimmed : `${trimmed} hrs`
}

export function TaskRow({
  epic,
  story,
  task,
  open,
  onToggle,
  onStatusChange,
  onPriorityChange,
  onAssigneeChange,
  onOpenDetail,
}: {
  epic: TreeEpic
  story: TreeStory
  task: TreeTask
  open: boolean
  onToggle: () => void
  onStatusChange: (dbId: number, status: string) => void
  onPriorityChange: (dbId: number, priority: Priority) => void
  onAssigneeChange: (dbId: number, value: string) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  const [assignee, setAssignee] = useState(task.assignee ?? '')

  return (
    <div className={styles.taskCard}>
      <div className={styles.taskHeader} onClick={onToggle}>
        <span className={styles.chevron}>{open ? '▾' : '▸'}</span>
        <span className={styles.idLabel}>{task.id}</span>
        <span
          className={`${styles.rowTitle} ${styles.rowTitleClickable}`}
          onClick={(e) => {
            e.stopPropagation()
            onOpenDetail({ kind: 'task', epic, story, task })
          }}
        >
          {task.title}
        </span>
        <PriorityBadge
          priority={task.priority}
          redmineName={task.redminePriorityName}
          onChange={task.dbId != null ? (next) => onPriorityChange(task.dbId!, next) : undefined}
        />
        <PrioritySourceNote priority={task.priority} redmineName={task.redminePriorityName} />
        {task.dbId != null ? (
          <StatusBadge
            status={task.status}
            options={TASK_STATUS_OPTIONS}
            onChange={(next) => onStatusChange(task.dbId!, next)}
          />
        ) : (
          <StaticStatusBadge status={task.status} />
        )}
      </div>
      {open && (
        <div className={styles.taskBody}>
          <p className={styles.taskDesc}>{task.description}</p>
          <div className={styles.taskDetailGrid}>
            <div className={styles.dodBox}>
              <span className={styles.dodLabel}>Definition of done</span>
              <span className={styles.dodValue}>{task.definitionOfDone || 'Not specified'}</span>
            </div>
            {task.estimateHours && (
              <div className={styles.estimateCard}>
                <span className={styles.metaLabel}>Estimate</span>
                <strong>{formatEstimate(task.estimateHours)}</strong>
              </div>
            )}
          </div>
          {task.dbId != null && (
            <div className={styles.assigneeRow}>
              <label htmlFor={`assignee-${task.dbId}`}>Assignee:</label>
              <input
                id={`assignee-${task.dbId}`}
                className={styles.assigneeInput}
                value={assignee}
                placeholder="Unassigned"
                onChange={(e) => setAssignee(e.target.value)}
                onBlur={() => onAssigneeChange(task.dbId!, assignee.trim())}
              />
            </div>
          )}
          {task.redmineId != null && (
            <p className={styles.redmineNote}>Redmine: #{task.redmineId}</p>
          )}
          <TestCasesPanel testCases={task.testCases} />
        </div>
      )}
    </div>
  )
}
