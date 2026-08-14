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
 * messages.
 *
 * Each epic's status depends only on its OWN counts, not on a frontier walk
 * over the epic list in order. main.py's phases used to complete strictly
 * epic-by-epic, so a contiguous-prefix "frontier" was a valid way to derive
 * a single "active" epic — but Phase 2/3/4 now dispatch every epic's calls
 * concurrently (EPIC_CONCURRENCY workers) and SSE events land in whatever
 * order the thread pool finishes them, not submission order. An epic later
 * in the list can finish before an earlier one, so a strict-order frontier
 * would incorrectly show a genuinely-done later epic as still pending.
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

  // "Has this phase started at all, for any epic?" — the signal a not-yet-
  // done epic uses to show a spinner instead of just sitting flat-pending.
  const storiesStarted = storyCountByEpic.size > 0
  const tasksStarted = taskCountByEpic.size > 0
  const testsStarted = testCountByEpic.size > 0

  return epics.map((epic) => {
    const storyCount = storyCountByEpic.get(epic.id) ?? 0
    const taskCount = taskCountByEpic.get(epic.id) ?? 0
    const testCount = testCountByEpic.get(epic.id) ?? 0

    const storiesStatus: PhaseStatus = storyCount > 0 ? 'done' : storiesStarted ? 'active' : 'pending'
    // Tasks can't start for an epic until it has stories; same for tests and tasks.
    const tasksStatus: PhaseStatus = storyCount === 0 ? 'pending' : taskCount > 0 ? 'done' : tasksStarted ? 'active' : 'pending'
    const testsStatus: PhaseStatus = taskCount === 0 ? 'pending' : testCount > 0 ? 'done' : testsStarted ? 'active' : 'pending'

    return { epic, storyCount, taskCount, testCount, storiesStatus, tasksStatus, testsStatus }
  })
}

/**
 * The "epics" phase itself has no per-epic row to hang a status off (an
 * epic can't track its own existence) — deriveEpicProgress above only ever
 * runs once epics already exist. This covers the phase before that: whether
 * epics have been generated at all yet. Unlike the other phases, "started
 * but not done" can't be inferred from data alone (an empty epics list
 * looks the same whether generation hasn't begun or is actively running),
 * so the caller's isGenerating flag disambiguates.
 */
export function deriveEpicsPhaseStatus(epicCount: number, isGenerating: boolean): PhaseStatus {
  if (epicCount > 0) return 'done'
  return isGenerating ? 'active' : 'pending'
}
