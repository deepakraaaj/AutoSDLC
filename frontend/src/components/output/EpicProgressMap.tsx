import { useMemo, useState } from 'react'
import type { Epic, Story, Task } from '../../types'
import { deriveEpicProgress, type PhaseStatus } from '../../lib/epicProgress'
import { Modal } from '../Modal'
import styles from './EpicProgressMap.module.css'

const ICON: Record<PhaseStatus, string> = { pending: '', active: '', done: '✓' }

type LivePhase = 'stories' | 'tasks' | 'tests'

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
    return <button type="button" className={className} onClick={onClick} title={`View generated ${label.toLowerCase()}`}>{content}</button>
  }
  return (
    <div className={className}>{content}</div>
  )
}

export function EpicProgressMap({ epics, stories, tasks }: { epics: Epic[]; stories: Story[]; tasks: Task[] }) {
  const rows = useMemo(() => deriveEpicProgress(epics, stories, tasks), [epics, stories, tasks])
  const [selection, setSelection] = useState<{ epic: Epic; phase: LivePhase } | null>(null)

  if (rows.length === 0) return null

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>Building your backlog — {epics.length} epics identified</div>
      <div className={styles.grid}>
        {rows.map((row) => (
          <div key={row.epic.id} className={`${styles.card} ${row.storiesStatus === 'active' || row.tasksStatus === 'active' || row.testsStatus === 'active' ? styles.cardActive : ''}`}>
            <div className={styles.title} title={row.epic.title}>
              {row.epic.title}
            </div>
            <div className={styles.phases}>
              <PhaseChip label="Stories" status={row.storiesStatus} count={row.storyCount} onClick={row.storyCount ? () => setSelection({ epic: row.epic, phase: 'stories' }) : undefined} />
              <PhaseChip label="Tasks" status={row.tasksStatus} count={row.taskCount} onClick={row.taskCount ? () => setSelection({ epic: row.epic, phase: 'tasks' }) : undefined} />
              <PhaseChip label="Tests" status={row.testsStatus} count={row.testCount} onClick={row.testCount ? () => setSelection({ epic: row.epic, phase: 'tests' }) : undefined} />
            </div>
          </div>
        ))}
      </div>
      {selection && (
        <LiveItemsModal
          epic={selection.epic}
          phase={selection.phase}
          stories={stories}
          tasks={tasks}
          onClose={() => setSelection(null)}
        />
      )}
    </div>
  )
}

function LiveItemsModal({ epic, phase, stories, tasks, onClose }: { epic: Epic; phase: LivePhase; stories: Story[]; tasks: Task[]; onClose: () => void }) {
  const epicStories = stories.filter((story) => story.epic_id === epic.id)
  const storyIds = new Set(epicStories.map((story) => story.id))
  const epicTasks = tasks.filter((task) => task.story_id && storyIds.has(task.story_id))

  return (
    <Modal open onClose={onClose} title={`${phase[0].toUpperCase()}${phase.slice(1)} generated so far`} subheader={epic.title}>
      <div className={styles.liveList}>
        {phase === 'stories' && epicStories.map((story) => (
          <article key={story.id} className={styles.liveItem}>
            <strong>{story.id}: {story.title}</strong>
            <p><em>{story.as_a}</em> → {story.i_want}</p>
            {story.acceptance_criteria.length > 0 && (
              <ul>{story.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>
            )}
          </article>
        ))}
        {phase === 'tasks' && epicTasks.map((task) => (
          <article key={task.id} className={styles.liveItem}>
            <strong>{task.id}: {task.title}</strong>
            <p>{task.description}</p>
            <small>Definition of done: {task.definition_of_done}</small>
          </article>
        ))}
        {phase === 'tests' && epicTasks.flatMap((task) => task.test_cases.map((test) => (
          <article key={`${task.id}-${test.id}`} className={styles.liveItem}>
            <strong>{test.id}: {test.title}</strong>
            <p>{test.description}</p>
            <small>Expected: {test.expected_result}</small>
          </article>
        )))}
      </div>
    </Modal>
  )
}
