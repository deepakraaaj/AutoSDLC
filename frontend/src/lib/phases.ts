import type { Phase } from '../hooks/useGeneration'
import type { GenerationOutput, Hierarchy } from '../types'
import { hierarchyIsPopulated, hierarchyToTree, outputToTree, type TreeEpic, type TreeStory, type TreeTask } from './tree'

export interface PhaseContent {
  tree: TreeEpic[]
  stories: { epic: TreeEpic; story: TreeStory }[]
  tasks: { epic: TreeEpic; story: TreeStory; task: TreeTask }[]
}

/** One flattening of a generation, shared by everything that shows it a phase at a
 * time — the step-by-step checkpoint (PhaseTabs) and the routed
 * /app/backlog/:id/:view pages both read from this rather than each walking the tree. */
export function phaseContent(output: GenerationOutput, hierarchy: Hierarchy | null): PhaseContent {
  const tree = hierarchyIsPopulated(hierarchy) ? hierarchyToTree(hierarchy!) : outputToTree(output)
  const stories = tree.flatMap((epic) => epic.stories.map((story) => ({ epic, story })))
  const tasks = stories.flatMap(({ epic, story }) => story.tasks.map((task) => ({ epic, story, task })))
  return { tree, stories, tasks }
}

export function phaseHasContent(content: PhaseContent): Record<Phase, boolean> {
  return {
    epics: content.tree.length > 0,
    stories: content.stories.length > 0,
    tasks: content.tasks.length > 0,
    tests: content.tasks.some(({ task }) => (task.testCases?.length ?? 0) > 0),
  }
}

/** Test cases live on tasks, so "how many test cases" is a sum, not a list length. */
export function phaseCount(content: PhaseContent, phase: Phase): number {
  if (phase === 'epics') return content.tree.length
  if (phase === 'stories') return content.stories.length
  if (phase === 'tasks') return content.tasks.length
  return content.tasks.reduce((n, { task }) => n + (task.testCases?.length ?? 0), 0)
}
