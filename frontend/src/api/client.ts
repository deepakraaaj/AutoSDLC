import type {
  AssistantChatResponse,
  AssistantPendingAction,
  BriefResources,
  BriefValidation,
  DashboardStats,
  GenerationOutput,
  Hierarchy,
  HistoryDetail,
  HistoryListItem,
  ProviderList,
  RedminePushResult,
  RedmineWorkspace,
  StreamEvent,
  TaskStatus,
  StoryStatus,
  EpicStatus,
  Priority,
  TokenEstimate,
} from '../types'

/** Same-origin in production (FastAPI serves the built app); the dev server
 * proxies these paths to the backend (see vite.config.ts). */
const BASE = ''

export function formatApiError(detail: unknown): string {
  if (detail == null) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(formatApiError).filter(Boolean).join('; ')
  if (typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    if (d.msg) {
      const loc = Array.isArray(d.loc) ? (d.loc as unknown[]).join('.') : ''
      return loc ? `${loc}: ${d.msg}` : String(d.msg)
    }
    if (d.message) return String(d.message)
    return Object.values(d).map(formatApiError).filter(Boolean).join('; ')
  }
  return String(detail)
}

export function getErrorMessage(payload: unknown, fallback: string): string {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  const p = payload as Record<string, unknown>
  if (p.detail !== undefined) return formatApiError(p.detail) || fallback
  if (p.message !== undefined) return formatApiError(p.message) || fallback
  return formatApiError(payload) || fallback
}

/** ApiError carries the parsed backend error payload so callers can show
 * severity/userAction, not just a message string. */
export class ApiError extends Error {
  status: number
  payload: unknown
  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

async function throwForStatus(res: Response, fallback: string): Promise<never> {
  let payload: unknown = null
  try {
    payload = await res.json()
  } catch {
    // non-JSON error body — fall through with fallback message
  }
  throw new ApiError(getErrorMessage(payload, fallback), res.status, payload)
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) await throwForStatus(res, `GET ${path} failed`)
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwForStatus(res, `POST ${path} failed`)
  return res.json() as Promise<T>
}

async function patchJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwForStatus(res, `PATCH ${path} failed`)
  return res.json() as Promise<T>
}

async function deleteJSON<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: 'DELETE' })
  if (!res.ok) await throwForStatus(res, `DELETE ${path} failed`)
  return res.json() as Promise<T>
}

// ── Health / brief resources ────────────────────────────────────────────

export function getHealth(): Promise<{ status: string; provider: string }> {
  return getJSON('/health')
}

export function getBriefResources(): Promise<BriefResources> {
  return getJSON('/brief-resources')
}

// ── AI provider settings ────────────────────────────────────────────────

export function getProviders(): Promise<ProviderList> {
  return getJSON('/providers')
}

/** Probes each configured provider's real API for its current quota
 * (~1-token request each) instead of returning this app's own tracked
 * usage — call on modal open and on demand, not on a tight poll. */
export function refreshProviders(): Promise<ProviderList> {
  return postJSON('/providers/refresh', {})
}

export function selectProvider(provider: string): Promise<ProviderList> {
  return postJSON('/providers/select', { provider })
}

export function validateBrief(text: string): Promise<BriefValidation> {
  return postJSON('/validate-brief', { text, clarification_answers: {} })
}

export function estimateTokens(text: string): Promise<TokenEstimate> {
  return postJSON('/estimate-tokens', { text, clarification_answers: {} })
}

// ── Clarify chat ─────────────────────────────────────────────────────────

export interface ClarifyChatResponse {
  needs_clarification: boolean
  questions: { question: string; why_it_matters: string }[]
  round: number
}

export function clarifyChat(
  text: string,
  qaHistory: { question: string; answer: string }[],
): Promise<ClarifyChatResponse> {
  return postJSON('/clarify-chat', { text, qa_history: qaHistory })
}

// ── Generation streaming (SSE over fetch, matching main.py's _sse format) ──

async function consumeSSE(
  res: Response,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    if (signal?.aborted) return
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        onEvent(JSON.parse(line.slice(6)) as StreamEvent)
      } catch {
        // malformed chunk — skip rather than kill the whole stream
      }
    }
  }
}

export async function streamGenerate(
  text: string,
  clarificationAnswers: Record<string, string>,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(BASE + '/generate-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, clarification_answers: clarificationAnswers }),
    signal,
  })
  if (!res.ok) await throwForStatus(res, 'Failed to start generation')
  await consumeSSE(res, onEvent, signal)
}

// ── Step-by-step generation (one phase per call, alongside streamGenerate) ─

export async function streamGenerateEpics(
  text: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(BASE + '/generate-epics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, clarification_answers: {} }),
    signal,
  })
  if (!res.ok) await throwForStatus(res, 'Failed to generate epics')
  await consumeSSE(res, onEvent, signal)
}

async function streamGeneratePhase(
  path: string,
  genId: number,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(BASE + `${path}/${genId}`, { method: 'POST', signal })
  if (!res.ok) await throwForStatus(res, `Failed to run ${path}`)
  await consumeSSE(res, onEvent, signal)
}

export function streamGenerateStories(genId: number, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  return streamGeneratePhase('/generate-stories', genId, onEvent, signal)
}

export function streamGenerateTasks(genId: number, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  return streamGeneratePhase('/generate-tasks', genId, onEvent, signal)
}

export function streamGenerateTestCases(genId: number, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  return streamGeneratePhase('/generate-test-cases', genId, onEvent, signal)
}

export async function streamGenerateFromFile(
  file: File,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(BASE + '/generate-from-file-stream', {
    method: 'POST',
    body: form,
    signal,
  })
  if (!res.ok) await throwForStatus(res, 'Failed to process uploaded file')
  await consumeSSE(res, onEvent, signal)
}

export async function extractBrief(file: File): Promise<{ text: string }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(BASE + '/extract-brief', { method: 'POST', body: form })
  if (!res.ok) await throwForStatus(res, 'Failed to read brief')
  return res.json() as Promise<{ text: string }>
}

// ── History ──────────────────────────────────────────────────────────────

export function listHistory(): Promise<{ generations: HistoryListItem[] }> {
  return getJSON('/history')
}

export function getHistoryItem(id: number): Promise<HistoryDetail> {
  return getJSON(`/history/${id}`)
}

export async function deleteHistoryItem(id: number): Promise<void> {
  const res = await fetch(BASE + `/history/${id}`, { method: 'DELETE' })
  if (!res.ok) await throwForStatus(res, 'Failed to delete generation')
}

export function getHierarchy(id: number): Promise<Hierarchy> {
  return getJSON(`/hierarchy/${id}`)
}

export function getDashboard(): Promise<DashboardStats> {
  return getJSON('/dashboard')
}

export function exportExcelUrl(id: number): string {
  return BASE + `/export-excel/${id}`
}

export function repairTaskDependencies(genId: number): Promise<{ repaired: boolean; output: GenerationOutput }> {
  return postJSON(`/generations/${genId}/repair-dependencies`, {})
}

export interface WeakDimension {
  name: string
  score: number
  reason: string
}

export interface WeakItem {
  kind: 'story' | 'task'
  id: string
  title: string
  weak_dimensions: WeakDimension[]
}

export interface FieldChange {
  field: string
  before: unknown
  after: unknown
}

export interface ImproveQualityItem {
  kind: 'story' | 'task'
  id: string
  title: string
  /** The item's *current* weak dimensions — refreshed after the fix, not the stale
   * pre-fix diagnosis. Empty once `resolved` is true; still non-empty (whatever's
   * genuinely still weak) when `updated` is true but `resolved` is false. */
  weak_dimensions: WeakDimension[]
  /** The rewrite was generated and written to the DB. Does NOT mean the item now
   * clears the quality bar — a dimension can move from 61% to 75% (real progress)
   * and still be below an 80% bar. Check `resolved` for that. */
  updated: boolean
  /** Only meaningful when `updated` is true: whether the item has zero weak
   * dimensions left after the rewrite. false means it still needs another pass. */
  resolved?: boolean
  /** Only present when `updated` is true: every dimension's real current score, not
   * just the weak ones — the pass bar only decides when we stop touching an item, the
   * model was never told to aim for exactly that number, so a resolved item can
   * genuinely land anywhere from the bar up to 100. */
  current_scores?: Record<string, number>
  /** The same dimensions scored *before* this request touched anything, so the UI can
   * show a real "55% → 78%" delta. Without it a bare current number is impossible to
   * read: "50%" looks like a result when it's often exactly where the item started. */
  before_scores?: Record<string, number>
  changes?: FieldChange[]
  error?: string
  /** Why `error` happened, and therefore how to present it. 'blocked' = the backlog
   * was deliberately left alone (the rewrite wasn't an improvement, the model had
   * nothing usable to offer); nothing broke and clicking Fix again does the same
   * thing. 'failed' = something actually went wrong and a retry may well work. */
  error_kind?: 'blocked' | 'failed'
  /** True when a round left the item's score exactly where it was, so the backend
   * stopped retrying it early rather than burning the remaining attempts. */
  stalled?: boolean
  /** How many times this item was retried within this one request — an item that
   * improved without clearing the bar is automatically retried against its own
   * current weak dimensions (up to the backend's max_attempts) instead of needing a
   * separate manual "Fix" click each time. */
  attempts?: number
}

export interface ImproveQualityResult {
  targeted: number
  updated: number
  /** How many of `updated` actually cleared the quality bar — can be less than
   * `updated`; the rest genuinely improved but are still weak on some dimension. */
  resolved: number
  items: ImproveQualityItem[]
  message?: string
  output?: GenerationOutput
}

export interface QualityItemSelection {
  kind: 'story' | 'task'
  id: string
}

/** Diagnosis only — no AI call, no write. Every specific story/task dragging the
 * score down, and *why* each one is weak — uncapped (up to a generous backend safety
 * ceiling), so the UI can group and let the user tick which ones to fix instead of a
 * blind top-N. Pass `dimension` (e.g. "definition_of_done") to narrow this to only
 * items weak on that one Scorecard bar — what the bar's own "Fix" link uses. See
 * main.py's GET /weak-items. */
export function getWeakItems(genId: number, dimension?: string): Promise<{ items: WeakItem[] }> {
  const query = dimension ? `?dimension=${encodeURIComponent(dimension)}` : ''
  return getJSON(`/generations/${genId}/weak-items${query}`)
}

/** Fixes exactly the items the user selected on the weak-items diagnosis, in place —
 * not a full regeneration. See main.py's POST /generations/{gen_id}/improve-quality. */
export function improveGenerationQuality(genId: number, items: QualityItemSelection[]): Promise<ImproveQualityResult> {
  return postJSON(`/generations/${genId}/improve-quality`, { items })
}

/** Live progress from a fix run. A run over a few dozen items does several rounds of
 * AI calls and can pause 20s+ waiting out a provider rate limit — long enough that a
 * silent spinner reads as a hang. `phase` says what kind of step this is; `message` is
 * ready to display. */
export interface ImproveQualityProgress {
  phase: 'start' | 'item' | 'round' | 'waiting' | 'scoring'
  total: number
  completed: number
  message: string
  round?: number
  max_rounds?: number
  seconds?: number
  title?: string
}

/** Streaming form of improveGenerationQuality: same final result, but reports each item
 * as it lands. Resolves with the result the run finished on, or throws if the server
 * sent an error event (or none at all). */
export async function streamImproveGenerationQuality(
  genId: number,
  items: QualityItemSelection[],
  onProgress: (progress: ImproveQualityProgress) => void,
  signal?: AbortSignal,
): Promise<ImproveQualityResult> {
  const res = await fetch(BASE + `/generations/${genId}/improve-quality-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
    signal,
  })
  if (!res.ok) await throwForStatus(res, 'Failed to start quality improvement')

  let result: ImproveQualityResult | null = null
  let failure: string | null = null
  await consumeSSE(res, (event) => {
    const e = event as unknown as { type: string } & Record<string, unknown>
    if (e.type === 'progress') onProgress(e as unknown as ImproveQualityProgress)
    else if (e.type === 'result') result = e as unknown as ImproveQualityResult
    else if (e.type === 'error') {
      const body = e.body as { error?: { message?: string } } | undefined
      failure = body?.error?.message ?? 'Quality improvement failed'
    }
  }, signal)

  if (failure) throw new Error(failure)
  if (!result) throw new Error('Quality improvement ended without a result')
  return result
}

// ── Status / assignee updates ───────────────────────────────────────────

export function updateEpicStatus(dbId: number, status: EpicStatus): Promise<unknown> {
  return patchJSON(`/epics/${dbId}/status`, { status })
}
export function updateStoryStatus(dbId: number, status: StoryStatus): Promise<unknown> {
  return patchJSON(`/stories/${dbId}/status`, { status })
}
export function updateTaskStatus(dbId: number, status: TaskStatus): Promise<unknown> {
  return patchJSON(`/tasks/${dbId}/status`, { status })
}
export function updateTaskAssignee(dbId: number, assignee: string | null): Promise<unknown> {
  return patchJSON(`/tasks/${dbId}/assignee`, { assignee })
}

// ── Priority updates ─────────────────────────────────────────────────────

export function updateEpicPriority(dbId: number, priority: Priority): Promise<unknown> {
  return patchJSON(`/epics/${dbId}/priority`, { priority })
}
export function updateStoryPriority(dbId: number, priority: Priority): Promise<unknown> {
  return patchJSON(`/stories/${dbId}/priority`, { priority })
}
export function updateTaskPriority(dbId: number, priority: Priority): Promise<unknown> {
  return patchJSON(`/tasks/${dbId}/priority`, { priority })
}

// ── Full content editing (title/description/acceptance criteria/etc) ──────

export interface EpicEditFields {
  title?: string
  description?: string
  feature_area?: string
}
export interface StoryEditFields {
  title?: string
  as_a?: string
  i_want?: string
  so_that?: string
  acceptance_criteria?: string[]
  feature_area?: string
}
export interface TaskEditFields {
  title?: string
  description?: string
  definition_of_done?: string
  estimate_hours?: string
  dependencies?: string[]
}

export function updateEpicContent(dbId: number, fields: EpicEditFields): Promise<unknown> {
  return patchJSON(`/epics/${dbId}`, fields)
}
export function updateStoryContent(dbId: number, fields: StoryEditFields): Promise<unknown> {
  return patchJSON(`/stories/${dbId}`, fields)
}
export function updateTaskContent(dbId: number, fields: TaskEditFields): Promise<unknown> {
  return patchJSON(`/tasks/${dbId}`, fields)
}

// ── Backlog CRUD ─────────────────────────────────────────────────────────

export interface CreateEpicFields extends Required<EpicEditFields> { generation_id: number; priority?: Priority }
export interface CreateStoryFields extends Required<StoryEditFields> { epic_id: number; size?: 'small' | 'medium' | 'large'; priority?: Priority }
export interface CreateTaskFields extends Required<TaskEditFields> { story_id: number; priority?: Priority }

export function createEpic(fields: CreateEpicFields): Promise<unknown> { return postJSON('/epics', fields) }
export function createStory(fields: CreateStoryFields): Promise<unknown> { return postJSON('/stories', fields) }
export function createTask(fields: CreateTaskFields): Promise<unknown> { return postJSON('/tasks', fields) }
export function deleteEpic(dbId: number): Promise<unknown> { return deleteJSON(`/epics/${dbId}`) }
export function deleteStory(dbId: number): Promise<unknown> { return deleteJSON(`/stories/${dbId}`) }
export function deleteTask(dbId: number): Promise<unknown> { return deleteJSON(`/tasks/${dbId}`) }

// ── Redmine ──────────────────────────────────────────────────────────────

export function listRedmineProjects(url: string, apiKey: string): Promise<RedmineWorkspace> {
  return postJSON('/redmine/projects/list', { redmine_url: url, redmine_api_key: apiKey })
}

export interface CreateRedmineProjectRequest {
  redmine_url: string
  redmine_api_key: string
  name: string
  identifier: string | null
  description: string
  parent_project_ref: string | null
}

export function createRedmineProject(
  req: CreateRedmineProjectRequest,
): Promise<{ project: Record<string, unknown> }> {
  return postJSON('/redmine/projects/create', req)
}

export interface PushToRedmineRequest {
  generation_id?: number
  output?: GenerationOutput
  redmine_url: string
  redmine_api_key: string
  redmine_project_id: string
  /** Scope the push to one epic and everything under it — used by "push
   * this" from a detail view instead of the whole backlog. Requires
   * generation_id (the backend ignores it with a plain `output` push). */
  epic_id?: string
}

export function pushToRedmine(req: PushToRedmineRequest): Promise<RedminePushResult> {
  return postJSON('/push-to-redmine', req)
}

// ── Assistant chat ───────────────────────────────────────────────────────

export interface AssistantChatRequest {
  message: string
  history: { role: 'user' | 'assistant'; content: string }[]
  redmine_url: string
  redmine_api_key: string
  redmine_project_id: string
  generation_id: number | null
  confirm?: boolean
  pending_action?: AssistantPendingAction
}

export function assistantChat(req: AssistantChatRequest): Promise<AssistantChatResponse> {
  return postJSON('/assistant/chat', req)
}
