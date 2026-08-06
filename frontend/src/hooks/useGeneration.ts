import { useCallback, useRef, useState } from 'react'
import {
  ApiError,
  estimateTokens,
  getHierarchy,
  getHistoryItem,
  streamGenerate,
  streamGenerateFromFile,
} from '../api/client'
import type { Epic, GenerationOutput, Hierarchy, Story, StreamEvent, Task } from '../types'
import { notifyGenerationDone, requestNotificationPermission } from '../lib/notify'
import { useToast } from './useToast'

export type GenStep = 'connecting' | 'generating' | 'parsing' | 'scoring' | 'done'

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
        case 'done':
          setState((s) => ({
            ...s,
            step: 'done',
            progressMessage: 'Done!',
            lastOutput: event.output,
            lastGenId: event.output.generation_id ?? null,
            hierarchy: null,
          }))
          if (event.output.generation_id) {
            void refreshHierarchy(event.output.generation_id)
          }
          notifyGenerationDone(
            `${event.output.epics.length} epics · ${event.output.stories.length} stories · ${event.output.tasks.length} tasks generated.`,
          )
          break
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
        progressMessage: `~${est.word_count} words · ~${est.estimated_calls} AI calls · est. ${est.estimated_time_seconds}s · ~$${est.cost_usd.toFixed(2)}`,
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
      setState({ ...INITIAL_STATE, isGenerating: true, step: 'connecting', progressMessage: 'Uploading…' })
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
    stop,
    reset,
    loadFromHistory,
    refreshHierarchy,
    dismissError,
  }
}

export type UseGenerationReturn = ReturnType<typeof useGeneration>
