import { useCallback, useRef, useState } from 'react'
import {
  ApiError,
  estimateTokens,
  getHierarchy,
  getHistoryItem,
  streamGenerate,
  streamGenerateEpics,
  streamGenerateFromFile,
  streamGenerateStories,
  streamGenerateTasks,
  streamGenerateTestCases,
} from '../api/client'
import type { Epic, GenerationOutput, Hierarchy, Story, StreamEvent, Task } from '../types'
import { notifyGenerationDone, requestNotificationPermission } from '../lib/notify'
import { useToast } from './useToast'

export type GenStep = 'connecting' | 'generating' | 'parsing' | 'scoring' | 'done'

/** Step-by-step generation phases, in run order. */
export type Phase = 'epics' | 'stories' | 'tasks' | 'tests'
const PHASE_SEQUENCE: Phase[] = ['epics', 'stories', 'tasks', 'tests']

export interface GenerationError {
  message: string
  userAction: string | null
}

interface GenerationState {
  isGenerating: boolean
  step: GenStep | null
  progressMessage: string
  /** Built live from 'epic'/'story'/'task' SSE events as generation runs —
   * this is what the in-progress view renders, distinct from lastOutput
   * (only set once, from the final 'done' event). */
  liveEpics: Epic[]
  liveStories: Story[]
  liveTasks: Task[]
  lastOutput: GenerationOutput | null
  lastGenId: number | null
  hierarchy: Hierarchy | null
  error: GenerationError | null
  /** Pre-generation estimate from /estimate-tokens, shown alongside a live
   * elapsed timer while generating. Server-measured actual time
   * (output.metrics.generation_seconds) is the source of truth once done —
   * this is just what the client had to go on beforehand. */
  estimatedSeconds: number | null
  /** Client timestamp (Date.now()) the stream actually started — drives the
   * live elapsed-time ticker in ProgressPanel. */
  startedAt: number | null
  /** Set only by the step-by-step flow (runPhase): the next phase the user
   * can click to run, or null when not in a step-by-step run (either the
   * one-click flow, or a step-by-step run that finished all 4 phases). */
  awaitingPhase: Phase | null
}

const INITIAL_STATE: GenerationState = {
  isGenerating: false,
  step: null,
  progressMessage: '',
  liveEpics: [],
  liveStories: [],
  liveTasks: [],
  lastOutput: null,
  lastGenId: null,
  hierarchy: null,
  error: null,
  estimatedSeconds: null,
  startedAt: null,
  awaitingPhase: null,
}

/** Append, or replace in place if an item with this id already exists
 * (Phase 4 re-sends a task once its test cases are attached). */
function upsertById<T extends { id: string }>(list: T[], item: T): T[] {
  const idx = list.findIndex((existing) => existing.id === item.id)
  if (idx === -1) return [...list, item]
  const next = list.slice()
  next[idx] = item
  return next
}

export function useGeneration() {
  const [state, setState] = useState<GenerationState>(INITIAL_STATE)
  const controllerRef = useRef<AbortController | null>(null)
  const { showToast } = useToast()

  const refreshHierarchy = useCallback(async (genId: number) => {
    try {
      const hierarchy = await getHierarchy(genId)
      setState((s) => ({ ...s, hierarchy }))
    } catch {
      // Non-fatal: the generated (non-DB) view already covers the output.
    }
  }, [])

  const handleEvent = useCallback(
    (event: StreamEvent) => {
      switch (event.type) {
        case 'status':
          setState((s) => ({
            ...s,
            step: (event.step as GenStep) ?? s.step,
            progressMessage: event.message ?? s.progressMessage,
          }))
          break
        case 'epic':
          setState((s) => ({ ...s, liveEpics: upsertById(s.liveEpics, event.epic) }))
          break
        case 'story':
          setState((s) => ({ ...s, liveStories: upsertById(s.liveStories, event.story) }))
          break
        case 'task':
          setState((s) => ({ ...s, liveTasks: upsertById(s.liveTasks, event.task) }))
          break
        case 'done': {
          // A step-by-step phase (event.phase set, not yet 'tests') is a
          // pause point, not a finish — update state but skip the
          // completion notification and hand control back to the "Generate
          // next phase" button instead of showing the final backlog view.
          // Each phase already persisted to the DB before sending 'done', so
          // the hierarchy refresh below runs either way — that's what gives
          // the step-by-step preview real db_ids (status editing, etc.)
          // instead of a read-only synthetic view.
          const isMidStepwiseRun = event.phase && event.phase !== 'tests'
          const nextPhase = event.phase ? PHASE_SEQUENCE[PHASE_SEQUENCE.indexOf(event.phase) + 1] ?? null : null
          setState((s) => ({
            ...s,
            step: isMidStepwiseRun ? s.step : 'done',
            progressMessage: isMidStepwiseRun ? s.progressMessage : 'Done!',
            lastOutput: event.output,
            lastGenId: event.output.generation_id ?? s.lastGenId,
            awaitingPhase: nextPhase,
          }))
          if (event.output.generation_id) {
            void refreshHierarchy(event.output.generation_id)
          }
          if (isMidStepwiseRun) break
          notifyGenerationDone(
            `${event.output.epics.length} epics · ${event.output.stories.length} stories · ${event.output.tasks.length} tasks generated.`,
          )
          break
        }
        case 'warning':
          showToast('⚠️ Warning', event.message, 'warning')
          break
        case 'error': {
          const err = event.error
          setState((s) => ({
            ...s,
            error: { message: err.message, userAction: err.userAction },
          }))
          const details = err.details ? `\nDetails: ${err.details}` : ''
          showToast(err.code || 'Error', `${err.message}${details}`, err.severity)
          break
        }
      }
    },
    [refreshHierarchy, showToast],
  )

  const beginRun = useCallback(async (text: string) => {
    requestNotificationPermission()
    setState({ ...INITIAL_STATE, isGenerating: true, step: 'connecting', progressMessage: 'Starting…' })
    try {
      const est = await estimateTokens(text)
      setState((s) => ({
        ...s,
        progressMessage: `~${est.word_count} words · ~${est.estimated_calls} AI calls · est. ${est.estimated_time_seconds}s · ~$${est.cost_usd.toFixed(4)}`,
        estimatedSeconds: est.estimated_time_seconds,
      }))
      await new Promise((r) => setTimeout(r, 1200))
    } catch {
      // Estimate is a nicety, not a requirement — proceed without it.
    }
  }, [])

  const runGenerate = useCallback(
    async (text: string, clarificationAnswers: Record<string, string> = {}) => {
      const controller = new AbortController()
      controllerRef.current = controller
      await beginRun(text)
      setState((s) => ({ ...s, startedAt: Date.now() }))
      try {
        await streamGenerate(text, clarificationAnswers, handleEvent, controller.signal)
      } catch (e) {
        if (controller.signal.aborted) return
        const message = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Unexpected error'
        setState((s) => ({ ...s, error: { message, userAction: null } }))
        showToast('Error', message, 'error')
      } finally {
        if (!controller.signal.aborted) setState((s) => ({ ...s, isGenerating: false }))
        if (controllerRef.current === controller) controllerRef.current = null
      }
    },
    [beginRun, handleEvent, showToast],
  )

  const runGenerateFromFile = useCallback(
    async (file: File) => {
      requestNotificationPermission()
      const controller = new AbortController()
      controllerRef.current = controller
      setState({ ...INITIAL_STATE, isGenerating: true, step: 'connecting', progressMessage: 'Uploading…', startedAt: Date.now() })
      try {
        await streamGenerateFromFile(file, handleEvent, controller.signal)
      } catch (e) {
        if (controller.signal.aborted) return
        const message = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Unexpected error'
        setState((s) => ({ ...s, error: { message, userAction: null } }))
        showToast('Error', message, 'error')
      } finally {
        if (!controller.signal.aborted) setState((s) => ({ ...s, isGenerating: false }))
        if (controllerRef.current === controller) controllerRef.current = null
      }
    },
    [handleEvent, showToast],
  )

  /** Runs one step-by-step phase. `text` is required (and genId ignored) for
   * 'epics', the first phase, which starts a brand-new generation — every
   * later phase takes the generation_id the 'epics' phase's 'done' event
   * returned instead. Live epics/stories/tasks accumulate across calls (not
   * reset between phases) so the partial-backlog preview keeps building. */
  const runPhase = useCallback(
    async (phase: Phase, genId: number | null, text?: string) => {
      const controller = new AbortController()
      controllerRef.current = controller
      if (phase === 'epics') {
        requestNotificationPermission()
        setState({ ...INITIAL_STATE, isGenerating: true, step: 'connecting', progressMessage: 'Starting…', startedAt: Date.now() })
      } else {
        setState((s) => ({ ...s, isGenerating: true, error: null }))
      }
      try {
        if (phase === 'epics') await streamGenerateEpics(text ?? '', handleEvent, controller.signal)
        else if (phase === 'stories') await streamGenerateStories(genId!, handleEvent, controller.signal)
        else if (phase === 'tasks') await streamGenerateTasks(genId!, handleEvent, controller.signal)
        else await streamGenerateTestCases(genId!, handleEvent, controller.signal)
      } catch (e) {
        if (controller.signal.aborted) return
        const message = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Unexpected error'
        setState((s) => ({ ...s, error: { message, userAction: null } }))
        showToast('Error', message, 'error')
      } finally {
        if (!controller.signal.aborted) setState((s) => ({ ...s, isGenerating: false }))
        if (controllerRef.current === controller) controllerRef.current = null
      }
    },
    [handleEvent, showToast],
  )

  const stop = useCallback(() => {
    controllerRef.current?.abort()
    setState((s) => ({ ...s, isGenerating: false, step: null }))
  }, [])

  const reset = useCallback(() => {
    controllerRef.current?.abort()
    setState(INITIAL_STATE)
  }, [])

  const loadFromHistory = useCallback(
    async (genId: number) => {
      try {
        const detail = await getHistoryItem(genId)
        setState({ ...INITIAL_STATE, lastOutput: detail.output, lastGenId: genId })
        await refreshHierarchy(genId)
      } catch (e) {
        const message = e instanceof ApiError ? e.message : 'Failed to load generation'
        showToast('Error', message, 'error')
      }
    },
    [refreshHierarchy, showToast],
  )

  const dismissError = useCallback(() => {
    setState((s) => ({ ...s, error: null }))
  }, [])

  return {
    state,
    runGenerate,
    runGenerateFromFile,
    runPhase,
    stop,
    reset,
    loadFromHistory,
    refreshHierarchy,
    dismissError,
  }
}

export type UseGenerationReturn = ReturnType<typeof useGeneration>
