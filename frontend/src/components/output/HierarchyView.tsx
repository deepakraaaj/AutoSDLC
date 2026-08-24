import { useEffect, useMemo, useState } from 'react'
import { filterTree, type TreeEpic } from '../../lib/tree'
import type { Priority } from '../../types'
import { EpicRow } from './EpicRow'
import type { DetailTarget } from './DetailModal'
import styles from './HierarchyView.module.css'

const EMPTY_SET: Set<string> = new Set()

function allTaskKeys(tree: TreeEpic[]): Set<string> {
  const keys = new Set<string>()
  for (const epic of tree) for (const story of epic.stories) for (const task of story.tasks) keys.add(task.key)
  return keys
}
function allEpicKeys(tree: TreeEpic[]): Set<string> {
  return new Set(tree.map((e) => e.key))
}
function allStoryKeys(tree: TreeEpic[]): Set<string> {
  const keys = new Set<string>()
  for (const epic of tree) for (const story of epic.stories) keys.add(story.key)
  return keys
}

export function HierarchyView({
  tree,
  focusStoryId = null,
  onEpicStatusChange,
  onStoryStatusChange,
  onTaskStatusChange,
  onEpicPriorityChange,
  onStoryPriorityChange,
  onTaskPriorityChange,
  onAssigneeChange,
  onOpenDetail,
}: {
  tree: TreeEpic[]
  focusStoryId?: string | null
  onEpicStatusChange: (dbId: number, status: string) => void
  onStoryStatusChange: (dbId: number, status: string) => void
  onTaskStatusChange: (dbId: number, status: string) => void
  onEpicPriorityChange: (dbId: number, priority: Priority) => void
  onStoryPriorityChange: (dbId: number, priority: Priority) => void
  onTaskPriorityChange: (dbId: number, priority: Priority) => void
  onAssigneeChange: (dbId: number, value: string) => void
  onOpenDetail: (target: DetailTarget) => void
}) {
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const [closedEpicKeys, setClosedEpicKeys] = useState<Set<string>>(EMPTY_SET)
  const [closedStoryKeys, setClosedStoryKeys] = useState<Set<string>>(EMPTY_SET)
  const [openTaskKeys, setOpenTaskKeys] = useState<Set<string>>(EMPTY_SET)
  const [allExpanded, setAllExpanded] = useState(false)

  useEffect(() => {
    if (focusStoryId) setQuery(focusStoryId)
  }, [focusStoryId])

  const filtering = Boolean(query.trim() || statusFilter || priorityFilter)
  const filteredTree = useMemo(
    () => (filtering ? filterTree(tree, query, statusFilter, priorityFilter) : tree),
    [tree, query, statusFilter, priorityFilter, filtering],
  )

  const totals = useMemo(() => {
    let stories = 0
    let tasks = 0
    for (const epic of filteredTree) {
      stories += epic.stories.length
      for (const story of epic.stories) tasks += story.tasks.length
    }
    return { epics: filteredTree.length, stories, tasks }
  }, [filteredTree])

  const effectiveClosedEpicKeys = filtering ? EMPTY_SET : closedEpicKeys
  const effectiveClosedStoryKeys = filtering ? EMPTY_SET : closedStoryKeys
  const effectiveOpenTaskKeys = filtering ? allTaskKeys(filteredTree) : openTaskKeys

  function toggleAll() {
    if (allExpanded) {
      setClosedEpicKeys(allEpicKeys(tree))
      setClosedStoryKeys(allStoryKeys(tree))
      setOpenTaskKeys(EMPTY_SET)
    } else {
      setClosedEpicKeys(EMPTY_SET)
      setClosedStoryKeys(EMPTY_SET)
      setOpenTaskKeys(allTaskKeys(tree))
    }
    setAllExpanded((v) => !v)
  }

  function toggleEpic(key: string) {
    setClosedEpicKeys((prev) => toggleInSet(prev, key))
  }
  function toggleStory(key: string) {
    setClosedStoryKeys((prev) => toggleInSet(prev, key))
  }
  function toggleTask(key: string) {
    setOpenTaskKeys((prev) => toggleInSet(prev, key))
  }

  return (
    <div>
      <div className={styles.toolbar}>
        <input
          className={`text-input ${styles.search}`}
          type="search"
          placeholder="Search epics, stories, tasks by ID or title…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select className="select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="planned">Planned</option>
          <option value="todo">Todo</option>
          <option value="in-progress">In progress</option>
          <option value="review">Review</option>
          <option value="testing">Testing</option>
          <option value="done">Done</option>
        </select>
        <select className="select" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
          <option value="">All priorities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <button className="btn btn-secondary btn-sm" onClick={toggleAll}>
          {allExpanded ? 'Collapse all' : 'Expand all'}
        </button>
      </div>

      {filtering && (
        <div className={styles.resultCount}>
          {totals.epics} epic{totals.epics === 1 ? '' : 's'} · {totals.stories} stor
          {totals.stories === 1 ? 'y' : 'ies'} · {totals.tasks} task{totals.tasks === 1 ? '' : 's'} matched
        </div>
      )}

      {filteredTree.length === 0 ? (
        <p className="text-muted">No matches.</p>
      ) : (
        filteredTree.map((epic) => (
          <EpicRow
            key={epic.key}
            epic={epic}
            open={!effectiveClosedEpicKeys.has(epic.key)}
            onToggle={() => toggleEpic(epic.key)}
            closedStoryKeys={effectiveClosedStoryKeys}
            onToggleStory={toggleStory}
            openTaskKeys={effectiveOpenTaskKeys}
            onToggleTask={toggleTask}
            onEpicStatusChange={onEpicStatusChange}
            onStoryStatusChange={onStoryStatusChange}
            onTaskStatusChange={onTaskStatusChange}
            onEpicPriorityChange={onEpicPriorityChange}
            onStoryPriorityChange={onStoryPriorityChange}
            onTaskPriorityChange={onTaskPriorityChange}
            onAssigneeChange={onAssigneeChange}
            onOpenDetail={onOpenDetail}
          />
        ))
      )}
    </div>
  )
}

function toggleInSet(set: Set<string>, key: string): Set<string> {
  const next = new Set(set)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  return next
}
