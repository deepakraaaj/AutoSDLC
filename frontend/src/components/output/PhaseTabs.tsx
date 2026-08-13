import { useState } from 'react'
import type { Phase } from '../../hooks/useGeneration'
import type { GenerationOutput, Hierarchy } from '../../types'
import { hierarchyIsPopulated, hierarchyToTree, outputToTree, type TreeEpic, type TreeStory } from '../../lib/tree'
import { PriorityBadge, PrioritySourceNote } from './PriorityBadge'
import { StatusBadge, StaticStatusBadge } from './StatusBadge'
import { TestCasesPanel } from './TestCasesPanel'
import type { DetailTarget } from './DetailModal'
import hstyles from './HierarchyTree.module.css'
import styles from './PhaseTabs.module.css'

const TABS: { id: Phase; label: string }[] = [
  { id: 'epics', label: 'Epics' },
  { id: 'stories', label: 'Stories' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'tests', label: 'Test Cases' },
]

/** What clicking "Generate" on a tab actually does — shown before the user
 * spends an AI call finding out, not after. */
const PHASE_DESCRIPTIONS: Record<Phase, string> = {
  epics: 'Extracts feature areas and epics from your brief.',
  stories: 'Generates 5-8 user stories per epic, with acceptance criteria.',
  tasks: 'Breaks each story into 4-6 implementation tasks.',
  tests: 'Generates manual test cases for every task.',
}

const EPIC_STATUS_OPTIONS = ['planned', 'in-progress', 'done']
const STORY_STATUS_OPTIONS = ['planned', 'in-progress', 'review', 'done']
const TASK_STATUS_OPTIONS = ['todo', 'in-progress', 'testing', 'done']

/** Step-by-step generation control, tab-flavored: one tab per phase
 * (Epics/Stories/Tasks/Test Cases), sequentially gated — a tab only opens
 * once its phase has data. Only rendered between phases — App.tsx gates
 * this out while a phase is actively generating, so ProgressPanel stays the
 * single "something is happening" indicator instead of the two overlapping.
 * Content per tab reuses the same badge/status controls EpicRow/StoryRow/
 * TaskRow already use (and the same HierarchyTree.module.css classes) —
 * just laid out as a flat per-phase list instead of a nested expand/collapse
 * tree, since that's the whole point of separating them into tabs. */
export function PhaseTabs({
  awaitingPhase,
  output,
  hierarchy,
  onGenerateNext,
  onEpicStatusChange,
  onStoryStatusChange,
  onTaskStatusChange,
  onOpenDetail,
}: {
  awaitingPhase: Phase
  output: GenerationOutput
  hierarchy: Hierarchy | null
  onGenerateNext: () => void
  onEpicStatusChange: (dbId: number, status: string) => void
  onStoryStatusChange: (dbId: number, status: string) => void
  onTaskStatusChange: (dbId: number, status: string) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  const frontierIndex = TABS.findIndex((t) => t.id === awaitingPhase)
  // Remounts fresh each time App.tsx toggles isGenerating (see the render
  // gate there) — that's what re-syncs `active` to the new frontier after
  // each phase completes, without needing an effect here.
  const [active, setActive] = useState<Phase>(awaitingPhase)

  const tree = hierarchyIsPopulated(hierarchy) ? hierarchyToTree(hierarchy!) : outputToTree(output)
  const stories = tree.flatMap((epic) => epic.stories.map((story) => ({ epic, story })))
  const tasks = stories.flatMap(({ epic, story }) => story.tasks.map((task) => ({ epic, story, task })))

  return (
    <div className={`card ${styles.box}`}>
      <div className={styles.tabBar} role="tablist" aria-label="Generation phase">
        {TABS.map((t, i) => {
          const unlocked = i <= frontierIndex
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active === t.id}
              disabled={!unlocked}
              className={`${styles.tab} ${active === t.id ? styles.tabActive : ''} ${i < frontierIndex ? styles.tabDone : ''}`}
              onClick={() => unlocked && setActive(t.id)}
              title={unlocked ? undefined : `Generate ${TABS[i - 1]?.label ?? 'the previous phase'} first`}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      <div className={styles.panel}>
        {active === awaitingPhase && (
          <div className={styles.generateRow}>
            <p className={styles.description}>{PHASE_DESCRIPTIONS[awaitingPhase]}</p>
            <button className="btn btn-primary btn-sm" onClick={onGenerateNext}>
              Generate {TABS[frontierIndex]?.label}
            </button>
          </div>
        )}

        {active === 'epics' &&
          (tree.length === 0 ? (
            <p className={styles.empty}>No epics yet.</p>
          ) : (
            tree.map((epic) => <EpicListItem key={epic.key} epic={epic} onStatusChange={onEpicStatusChange} onOpenDetail={onOpenDetail} />)
          ))}

        {active === 'stories' &&
          (stories.length === 0 ? (
            <p className={styles.empty}>No stories yet.</p>
          ) : (
            stories.map(({ epic, story }) => (
              <StoryListItem key={story.key} epic={epic} story={story} onStatusChange={onStoryStatusChange} onOpenDetail={onOpenDetail} />
            ))
          ))}

        {(active === 'tasks' || active === 'tests') &&
          (tasks.length === 0 ? (
            <p className={styles.empty}>No tasks yet.</p>
          ) : (
            tasks.map(({ epic, story, task }) => (
              <div key={task.key} className={hstyles.taskCard}>
                <div className={hstyles.taskHeader} onClick={() => onOpenDetail({ kind: 'task', epic, story, task })}>
                  <span className={hstyles.idLabel}>{task.id}</span>
                  <span className={`${hstyles.rowTitle} ${hstyles.rowTitleClickable}`}>{task.title}</span>
                  <PriorityBadge priority={task.priority} redmineName={task.redminePriorityName} />
                  <PrioritySourceNote priority={task.priority} redmineName={task.redminePriorityName} />
                  {task.dbId != null ? (
                    <StatusBadge status={task.status} options={TASK_STATUS_OPTIONS} onChange={(next) => onTaskStatusChange(task.dbId!, next)} />
                  ) : (
                    <StaticStatusBadge status={task.status} />
                  )}
                </div>
                {active === 'tests' && (
                  <div className={hstyles.taskBody}>
                    <TestCasesPanel testCases={task.testCases} />
                  </div>
                )}
              </div>
            ))
          ))}
      </div>
    </div>
  )
}

function EpicListItem({
  epic,
  onStatusChange,
  onOpenDetail,
}: {
  epic: TreeEpic
  onStatusChange: (dbId: number, status: string) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  return (
    <div className={hstyles.epicCard}>
      <div className={hstyles.epicHeader} onClick={() => onOpenDetail({ kind: 'epic', epic })}>
        {epic.id && <span className={hstyles.idLabel}>{epic.id}</span>}
        <span className={`${hstyles.rowTitle} ${hstyles.rowTitleClickable}`}>{epic.title}</span>
        <PriorityBadge priority={epic.priority} redmineName={epic.redminePriorityName} />
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
  onOpenDetail,
}: {
  epic: TreeEpic
  story: TreeStory
  onStatusChange: (dbId: number, status: string) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  return (
    <div className={hstyles.storyCard}>
      <div className={hstyles.storyHeader} onClick={() => onOpenDetail({ kind: 'story', epic, story })}>
        <span className={hstyles.idLabel}>{story.id}</span>
        <span className={`${hstyles.rowTitle} ${hstyles.rowTitleClickable}`}>{story.title}</span>
        <PriorityBadge priority={story.priority} redmineName={story.redminePriorityName} />
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
