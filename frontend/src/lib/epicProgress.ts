import type { Epic, Story, Task } from '../types'

export type PhaseStatus = 'pending' | 'active' | 'done'

export interface EpicProgressRow {
  epic: Epic
  storyCount: number
  taskCount: number
  testCount: number
  storiesStatus: PhaseStatus
  tasksStatus: PhaseStatus
  testsStatus: PhaseStatus
}

/**
 * Turns the live epics/stories/tasks arrays into a per-epic "which phase is
 * this one in" reading, purely from data — no text-matching against status
 * messages. This works because main.py's phases are atomic across all
 * epics: Phase 2 (stories) fully finishes for every epic before Phase 3
 * (tasks) starts for any epic, and same for Phase 3 -> Phase 4 (tests). So
 * "done" / "active" / "pending" per epic per phase is just a frontier walk
 * over the epic list in order, skipping epics a phase never touches (an
 * epic with 0 stories never gets a tasks turn, matching the backend's
 * `if not epic_stories: continue`).
 */
export function deriveEpicProgress(epics: Epic[], stories: Story[], tasks: Task[]): EpicProgressRow[] {
  const storyCountByEpic = new Map<string, number>()
  for (const s of stories) {
    if (!s.epic_id) continue
    storyCountByEpic.set(s.epic_id, (storyCountByEpic.get(s.epic_id) ?? 0) + 1)
  }

  const epicIdByStoryId = new Map(stories.map((s) => [s.id, s.epic_id]))
  const taskCountByEpic = new Map<string, number>()
  const testCountByEpic = new Map<string, number>()
  for (const t of tasks) {
    const epicId = t.story_id ? epicIdByStoryId.get(t.story_id) : null
    if (!epicId) continue
    taskCountByEpic.set(epicId, (taskCountByEpic.get(epicId) ?? 0) + 1)
    if (t.test_cases.length) {
      testCountByEpic.set(epicId, (testCountByEpic.get(epicId) ?? 0) + t.test_cases.length)
    }
  }

  const allIds = epics.map((e) => e.id)
  const storiesDone = new Set(allIds.filter((id) => (storyCountByEpic.get(id) ?? 0) > 0))
  const storiesFrontier = frontier(allIds, storiesDone)

  const idsWithStories = allIds.filter((id) => storiesDone.has(id))
  const tasksDone = new Set(idsWithStories.filter((id) => (taskCountByEpic.get(id) ?? 0) > 0))
  const tasksFrontier = frontier(idsWithStories, tasksDone)

  const idsWithTasks = idsWithStories.filter((id) => tasksDone.has(id))
  const testsDone = new Set(idsWithTasks.filter((id) => (testCountByEpic.get(id) ?? 0) > 0))
  const testsFrontier = frontier(idsWithTasks, testsDone)

  return epics.map((epic) => {
    const statusOf = (done: Set<string>, activeId: string | null): PhaseStatus =>
      done.has(epic.id) ? 'done' : activeId === epic.id ? 'active' : 'pending'

    return {
      epic,
      storyCount: storyCountByEpic.get(epic.id) ?? 0,
      taskCount: taskCountByEpic.get(epic.id) ?? 0,
      testCount: testCountByEpic.get(epic.id) ?? 0,
      storiesStatus: statusOf(storiesFrontier.done, storiesFrontier.active),
      tasksStatus: idsWithStories.includes(epic.id) ? statusOf(tasksFrontier.done, tasksFrontier.active) : 'pending',
      testsStatus: idsWithTasks.includes(epic.id) ? statusOf(testsFrontier.done, testsFrontier.active) : 'pending',
    }
  })
}

function frontier(orderedIds: string[], doneIds: Set<string>): { done: Set<string>; active: string | null } {
  const done = new Set<string>()
  let active: string | null = null
  for (const id of orderedIds) {
    if (doneIds.has(id)) {
      done.add(id)
    } else {
      active = id
      break
    }
  }
  return { done, active }
}
