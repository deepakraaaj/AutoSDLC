import type { GenerationOutput, Hierarchy, TestCase } from '../types'

/**
 * The backend hands back two different shapes for "the backlog": the raw
 * GenerationOutput (flat epics/stories/tasks arrays, no db_id yet) right
 * after streaming finishes, and the DB-backed Hierarchy (nested, with
 * db_id/redmine fields) a moment later once it's persisted. The old app had
 * two parallel render functions with duplicated template strings for this.
 * Normalizing both into one shape here means the view only has one to deal
 * with, and status/assignee editing only lights up once a real db_id exists
 * to persist against — a task with no db_id yet shows a plain badge instead
 * of a control that silently wouldn't save.
 */

export interface TreeTask {
  key: string
  id: string
  dbId: number | null
  title: string
  description: string
  definitionOfDone: string
  estimateHours: string
  dependencies: string[]
  status: string
  priority: string
  redminePriorityName: string | null
  assignee: string | null
  redmineId: number | string | null
  testCases: TestCase[]
}

export interface TreeStory {
  key: string
  id: string
  dbId: number | null
  title: string
  asA: string
  iWant: string
  soThat: string
  acceptanceCriteria: string[]
  featureArea: string
  status: string
  priority: string
  redminePriorityName: string | null
  redmineId: number | string | null
  tasks: TreeTask[]
}

export interface TreeEpic {
  key: string
  id: string
  dbId: number | null
  title: string
  description: string
  featureArea: string
  status: string
  priority: string
  redminePriorityName: string | null
  redmineId: number | string | null
  stories: TreeStory[]
}

export function hierarchyToTree(hierarchy: Hierarchy): TreeEpic[] {
  return (hierarchy.epics || []).map((epic) => ({
    key: `epic-${epic.db_id}`,
    id: epic.issue_id || epic.ai_id || epic.id,
    dbId: epic.db_id,
    title: epic.title,
    description: epic.description,
    featureArea: epic.feature_area,
    status: epic.status,
    priority: epic.priority,
    redminePriorityName: epic.redmine_priority_name ?? null,
    redmineId: epic.redmine_id ?? null,
    stories: (epic.stories || []).map((story) => ({
      key: `story-${story.db_id}`,
      id: story.issue_id || story.ai_id || story.id,
      dbId: story.db_id,
      title: story.title,
      asA: story.as_a,
      iWant: story.i_want,
      soThat: story.so_that,
      acceptanceCriteria: story.acceptance_criteria || [],
      featureArea: story.feature_area,
      status: story.status,
      priority: story.priority,
      redminePriorityName: story.redmine_priority_name ?? null,
      redmineId: story.redmine_id ?? null,
      tasks: (story.tasks || []).map((task) => ({
        key: `task-${task.db_id}`,
        id: task.issue_id || task.ai_id || task.id,
        dbId: task.db_id,
        title: task.title,
        description: task.description,
        definitionOfDone: task.definition_of_done,
        estimateHours: task.estimate_hours,
        dependencies: task.dependencies || [],
        status: task.status,
        priority: task.priority,
        redminePriorityName: task.redmine_priority_name ?? null,
        assignee: task.assignee,
        redmineId: task.redmine_id ?? null,
        testCases: task.test_cases || [],
      })),
    })),
  }))
}

export function outputToTree(output: GenerationOutput): TreeEpic[] {
  const stories = output.stories || []
  const tasks = output.tasks || []
  const epics = output.epics || []

  if (!epics.length) {
    // No epics at all (rule-based flat output, or a degenerate case) —
    // synthesize a single unlabeled group so stories/tasks still render.
    return [
      {
        key: 'epic-flat',
        id: '',
        dbId: null,
        title: 'Ungrouped',
        description: '',
        featureArea: '',
        status: 'planned',
        priority: 'medium',
        redminePriorityName: null,
        redmineId: null,
        stories: stories.map((story) => storyToTree(story, tasks)),
      },
    ]
  }

  return epics.map((epic) => ({
    key: `epic-${epic.id}`,
    id: epic.id,
    dbId: null,
    title: epic.title,
    description: epic.description,
    featureArea: epic.feature_area,
    status: epic.status,
    priority: epic.priority,
    redminePriorityName: null,
    redmineId: null,
    stories: stories
      .filter((s) => s.epic_id === epic.id)
      .map((story) => storyToTree(story, tasks)),
  }))
}

function storyToTree(story: GenerationOutput['stories'][number], allTasks: GenerationOutput['tasks']): TreeStory {
  return {
    key: `story-${story.id}`,
    id: story.id,
    dbId: null,
    title: story.title,
    asA: story.as_a,
    iWant: story.i_want,
    soThat: story.so_that,
    acceptanceCriteria: story.acceptance_criteria || [],
    featureArea: story.feature_area,
    status: story.status,
    priority: story.priority,
    redminePriorityName: null,
    redmineId: null,
    tasks: allTasks
      .filter((t) => t.story_id === story.id)
      .map((task) => ({
        key: `task-${task.id}`,
        id: task.id,
        dbId: null,
        title: task.title,
        description: task.description,
        definitionOfDone: task.definition_of_done,
        estimateHours: task.estimate_hours,
        dependencies: task.dependencies || [],
        status: task.status,
        priority: task.priority,
        redminePriorityName: null,
        assignee: task.assignee,
        redmineId: null,
        testCases: task.test_cases || [],
      })),
  }
}

/** True if `hierarchy` actually has nested rows (vs. an empty/not-yet-loaded shell). */
export function hierarchyIsPopulated(hierarchy: Hierarchy | null): boolean {
  return !!hierarchy?.epics?.some((e) => Array.isArray(e.stories))
}

export interface TreeMatch {
  epic: TreeEpic
  matchedStories: TreeStory[]
}

/** Case-insensitive substring search across epic/story/task id+title, plus
 * status/priority filters. Returns only epics that have at least one
 * matching story after filtering, with their story list pre-filtered. */
export function filterTree(
  epics: TreeEpic[],
  query: string,
  statusFilter: string,
  priorityFilter: string,
): TreeEpic[] {
  const q = query.trim().toLowerCase()

  const matchesLeaf = (id: string, title: string, status: string, priority: string) => {
    if (statusFilter && status !== statusFilter) return false
    if (priorityFilter && priority !== priorityFilter) return false
    if (!q) return true
    return id.toLowerCase().includes(q) || title.toLowerCase().includes(q)
  }

  const result: TreeEpic[] = []
  for (const epic of epics) {
    const filteredStories: TreeStory[] = []
    for (const story of epic.stories) {
      const filteredTasks = story.tasks.filter((t) => matchesLeaf(t.id, t.title, t.status, t.priority))
      const storySelfMatches = matchesLeaf(story.id, story.title, story.status, story.priority)
      if (filteredTasks.length > 0 || (storySelfMatches && !statusFilter && !priorityFilter) || (storySelfMatches && q)) {
        filteredStories.push({ ...story, tasks: filteredTasks.length > 0 ? filteredTasks : story.tasks })
      }
    }
    const epicSelfMatches = matchesLeaf(epic.id, epic.title, epic.status, epic.priority)
    if (filteredStories.length > 0 || (epicSelfMatches && !q && !statusFilter && !priorityFilter)) {
      result.push({ ...epic, stories: filteredStories.length > 0 ? filteredStories : epic.stories })
    }
  }
  return result
}
