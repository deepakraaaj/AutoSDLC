import type {
  AddedProjectRepo,
  AssistantChatResponse,
  AssistantPendingAction,
  BitbucketPushResult,
  BitbucketRepoStatus,
  BriefResources,
  BriefValidation,
  CodeReviewEvent,
  DashboardStats,
  GenerationOutput,
  Hierarchy,
  HistoryDetail,
  HistoryListItem,
  IntegrationsStatus,
  ProjectDetail,
  ProjectListItem,
  PRSecurityScanResult,
  ProjectPullRequests,
  ProjectRepo,
  ProjectSecurity,
  ProjectSettings,
  ProjectSettingsUpdate,
  ProjectWiki,
  SprintPlan,
  SprintPlanInput,
  ProviderList,
  RedminePushResult,
  RedmineWorkspace,
  StreamEvent,
  TaskStatus,
  StoryStatus,
  EpicStatus,
  Priority,
  TokenEstimate,
  UsageLogEntry,
  UsageSummary,
  WikiPage,
  WikiGenerationResult,
  ProjectWikiChapterSet,
} from '../types'

/** Same-origin in production (FastAPI serves the built app); the dev server
 * proxies these paths to the backend (see vite.config.ts). */
const BASE = ''
const API_TIMEOUT_MS = 30_000
const JOB_INACTIVITY_MS = 180_000

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

async function boundedFetch(path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS)
  try {
    return await fetch(BASE + path, { ...init, signal: controller.signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(`The backend did not respond within ${API_TIMEOUT_MS / 1000} seconds. Check that the server is healthy, then retry.`, 408, null)
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await boundedFetch(path)
  if (!res.ok) await throwForStatus(res, `GET ${path} failed`)
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await boundedFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwForStatus(res, `POST ${path} failed`)
  return res.json() as Promise<T>
}

async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await boundedFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwForStatus(res, `PUT ${path} failed`)
  return res.json() as Promise<T>
}

async function patchJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await boundedFetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwForStatus(res, `PATCH ${path} failed`)
  return res.json() as Promise<T>
}

async function deleteJSON<T>(path: string): Promise<T> {
  const res = await boundedFetch(path, { method: 'DELETE' })
  if (!res.ok) await throwForStatus(res, `DELETE ${path} failed`)
  return res.json() as Promise<T>
}

const ACTIVE_JOB_STORAGE_KEY = 'autosdlc-active-job'

interface BackgroundJob {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  error: string | null
}

/** Generic over the event union so this same poller drives both generation
 * jobs (StreamEvent) and Bitbucket review jobs (CodeReviewEvent, see
 * reviewBitbucketPullRequest below) — both are just app/services/jobs.py
 * job ids with a /events endpoint underneath, only the payload shape
 * differs. `trackActive` opts out review jobs from the generation-resume
 * sessionStorage slot, which is generation-specific (resumeActiveGenerationJob). */
async function pollGenerationJob<E extends { type: string }>(
  jobId: string,
  onEvent: (event: E) => void,
  signal?: AbortSignal,
  cancelOnAbort = true,
  trackActive = true,
): Promise<void> {
  if (trackActive) sessionStorage.setItem(ACTIVE_JOB_STORAGE_KEY, jobId)
  let after = 0
  let terminal = false
  let lastActivityAt = Date.now()
  let previousStatus: BackgroundJob['status'] | null = null
  try {
    while (true) {
      if (signal?.aborted) {
        if (cancelOnAbort) {
          await boundedFetch(`/jobs/${jobId}`, { method: 'DELETE' }).catch(() => undefined)
          terminal = true
        }
        return
      }
      const batch = await getJSON<{ events: { seq: number; type: string; payload: Record<string, unknown> }[] }>(
        `/jobs/${jobId}/events?after=${after}`,
      )
      for (const item of batch.events) {
        after = Math.max(after, item.seq)
        lastActivityAt = Date.now()
        onEvent({ type: item.type, ...item.payload } as E)
      }
      const job = await getJSON<BackgroundJob>(`/jobs/${jobId}`)
      if (job.status !== previousStatus) {
        previousStatus = job.status
        lastActivityAt = Date.now()
      }
      if (job.status === 'succeeded') {
        terminal = true
        return
      }
      if (job.status === 'failed' || job.status === 'cancelled') {
        terminal = true
        throw new ApiError(job.error || `Job ${job.status}`, 500, job)
      }
      if (Date.now() - lastActivityAt > JOB_INACTIVITY_MS) {
        await boundedFetch(`/jobs/${jobId}`, { method: 'DELETE' }).catch(() => undefined)
        terminal = true
        throw new ApiError('This job reported no progress for 3 minutes and was stopped. Retry it, or check the backend and integration credentials.', 408, job)
      }
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  } finally {
    if (trackActive && terminal) sessionStorage.removeItem(ACTIVE_JOB_STORAGE_KEY)
  }
}

export async function resumeActiveGenerationJob(
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<boolean> {
  const jobId = sessionStorage.getItem(ACTIVE_JOB_STORAGE_KEY)
  if (!jobId) return false
  await pollGenerationJob(jobId, onEvent, signal, false)
  return true
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
  projectId?: number | null,
): Promise<void> {
  const job = await postJSON<BackgroundJob>('/jobs/generations', {
    text,
    clarification_answers: clarificationAnswers,
    ...(projectId ? { project_id: projectId } : {}),
  })
  await pollGenerationJob(job.id, onEvent, signal)
}

// ── Step-by-step generation (one phase per call, alongside streamGenerate) ─

export async function streamGenerateEpics(
  text: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
  projectId?: number | null,
): Promise<void> {
  const job = await postJSON<BackgroundJob>('/jobs/phases', { phase: 'epics', text, ...(projectId ? { project_id: projectId } : {}) })
  await pollGenerationJob(job.id, onEvent, signal)
}

async function streamGeneratePhase(
  phase: 'stories' | 'tasks' | 'tests',
  genId: number,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const job = await postJSON<BackgroundJob>('/jobs/phases', { phase, generation_id: genId })
  await pollGenerationJob(job.id, onEvent, signal)
}

export function streamGenerateStories(genId: number, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  return streamGeneratePhase('stories', genId, onEvent, signal)
}

export function streamGenerateTasks(genId: number, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  return streamGeneratePhase('tasks', genId, onEvent, signal)
}

export function streamGenerateTestCases(genId: number, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  return streamGeneratePhase('tests', genId, onEvent, signal)
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

// ── Projects ─────────────────────────────────────────────────────────────
// Project is a first-class entity (app/api/projects.py) — created before
// any generation, can hold N repos, optional "init the repo" verification
// on add.

export function createProject(name: string, description = '', ticketPrefix = ''): Promise<ProjectListItem> {
  return postJSON('/projects', { name, description, ticket_prefix: ticketPrefix })
}

export function listProjects(): Promise<{ projects: ProjectListItem[] }> {
  return getJSON('/projects')
}

export function getProject(projectId: number): Promise<ProjectDetail> {
  return getJSON(`/projects/${projectId}`)
}

export interface ProjectUpdateFields {
  name?: string
  description?: string
  ticket_prefix?: string
}

export function updateProject(projectId: number, fields: ProjectUpdateFields): Promise<ProjectDetail> {
  return putJSON(`/projects/${projectId}`, fields)
}

export function deleteProject(projectId: number): Promise<{ deleted: boolean }> {
  return deleteJSON(`/projects/${projectId}`)
}

export interface AddProjectRepoRequest {
  workspace: string
  repo_slug: string
  label?: string
  /** Whether to attempt a Bitbucket connectivity check on add — "init the
   * repo". Optional: a repo can be linked without ever being verified. */
  verify?: boolean
  /** Branch VAPT scans and repo-context reads snapshot; blank = the repo's
   * Bitbucket-configured default branch. */
  scan_branch?: string
}

export function addProjectRepo(projectId: number, req: AddProjectRepoRequest): Promise<AddedProjectRepo> {
  return postJSON(`/projects/${projectId}/repos`, req)
}

export interface UpdateProjectRepoRequest {
  workspace?: string
  repo_slug?: string
  label?: string
  scan_branch?: string
}

export function updateProjectRepo(projectId: number, repoId: number, req: UpdateProjectRepoRequest): Promise<ProjectRepo> {
  return putJSON(`/projects/${projectId}/repos/${repoId}`, req)
}

export function deleteProjectRepo(projectId: number, repoId: number): Promise<{ deleted: boolean }> {
  return deleteJSON(`/projects/${projectId}/repos/${repoId}`)
}

/** Automates prompts/EXTRACT_FROM_REPO.md's manual workflow: builds a brief
 * from the project's linked repositories (reconciled with `existingBrief`,
 * whatever's already in the editor) instead of a hand-authored markdown file. */
export function generateProjectBriefFromRepo(
  projectId: number,
  existingBrief: string,
): Promise<{ brief_text: string; repos_used: string[] }> {
  return postJSON(`/projects/${projectId}/brief/from-repo`, { existing_brief: existingBrief })
}

export function getProjectSettings(projectId: number): Promise<ProjectSettings> {
  return getJSON(`/projects/${projectId}/settings`)
}

export function updateProjectSettings(projectId: number, fields: ProjectSettingsUpdate): Promise<ProjectSettings> {
  return putJSON(`/projects/${projectId}/settings`, fields)
}

export function listProjectSprints(projectId: number): Promise<{ sprints: SprintPlan[] }> {
  return getJSON(`/projects/${projectId}/sprints`)
}

export function createProjectSprint(projectId: number, input: SprintPlanInput): Promise<SprintPlan> {
  return postJSON(`/projects/${projectId}/sprints`, input)
}

export function updateProjectSprint(projectId: number, sprintId: number, input: SprintPlanInput): Promise<SprintPlan> {
  return putJSON(`/projects/${projectId}/sprints/${sprintId}`, input)
}

export function deleteProjectSprint(projectId: number, sprintId: number): Promise<{ deleted: boolean }> {
  return deleteJSON(`/projects/${projectId}/sprints/${sprintId}`)
}

// One request, one response — no streaming/job machinery, same shape as
// updateProjectSettings above. A wiki generation is a single bounded LLM
// call, not the multi-phase pipeline useGeneration is built for.
export function getProjectWiki(projectId: number): Promise<ProjectWiki> {
  return getJSON(`/projects/${projectId}/wiki`)
}

type WikiJobEvent = { type: 'status'; message: string } | { type: 'done'; page: WikiPage } | { type: 'clarification'; questions: import('../types').WikiClarificationQuestion[] }

async function runWikiJob(path: string, onProgress?: (message: string) => void, clarificationAnswers: Record<string, string> = {}): Promise<WikiGenerationResult> {
  const job = await postJSON<BackgroundJob>(path, { clarification_answers: clarificationAnswers })
  let page: WikiPage | null = null
  let questions: import('../types').WikiClarificationQuestion[] | null = null
  await pollGenerationJob<WikiJobEvent>(job.id, (event) => {
    if (event.type === 'status') onProgress?.(event.message)
    if (event.type === 'done') page = event.page
    if (event.type === 'clarification') questions = event.questions
  }, undefined, true, false)
  if (questions) return { needs_clarification: true, questions }
  if (!page) throw new ApiError('Wiki job completed without a page or clarification questions.', 500, job)
  return { needs_clarification: false, page }
}

export function generateProjectWiki(projectId: number, onProgress?: (message: string) => void, clarificationAnswers?: Record<string, string>): Promise<WikiGenerationResult> {
  return runWikiJob(`/projects/${projectId}/wiki/generate-job`, onProgress, clarificationAnswers)
}

export function generateRepoWiki(projectId: number, repoId: number, onProgress?: (message: string) => void, clarificationAnswers?: Record<string, string>): Promise<WikiGenerationResult> {
  return runWikiJob(`/projects/${projectId}/repos/${repoId}/wiki/generate-job`, onProgress, clarificationAnswers)
}

// ── Multi-chapter wiki (app/services/wiki_chapters.py) ───────────────────
// Additive alongside the flat-page functions above, which stay untouched.

/** Null when no chapter wiki has been built yet for this project (backend
 * 404) — a real "not built" state, not an error to surface as a toast. */
export async function getProjectChapterWiki(projectId: number): Promise<ProjectWikiChapterSet | null> {
  try {
    return await getJSON<ProjectWikiChapterSet>(`/projects/${projectId}/wiki-chapters`)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

type ChapterWikiJobEvent = { type: 'status'; message: string } | { type: 'done'; chapter_set: ProjectWikiChapterSet }

export async function generateProjectChapterWiki(projectId: number, onProgress?: (message: string) => void): Promise<ProjectWikiChapterSet> {
  const job = await postJSON<BackgroundJob>(`/projects/${projectId}/wiki-chapters/generate-job`, {})
  let chapterSet: ProjectWikiChapterSet | null = null
  await pollGenerationJob<ChapterWikiJobEvent>(job.id, (event) => {
    if (event.type === 'status') onProgress?.(event.message)
    if (event.type === 'done') chapterSet = event.chapter_set
  }, undefined, true, false)
  if (!chapterSet) throw new ApiError('Chapter wiki job completed without a result.', 500, job)
  return chapterSet
}

// ── Pull requests ────────────────────────────────────────────────────────

export function listProjectPullRequests(projectId: number): Promise<ProjectPullRequests> {
  return getJSON(`/projects/${projectId}/pull-requests`)
}

/** Schedules the same 'bitbucket_review' job the webhook runs automatically
 * — for re-reviewing a PR, or reviewing one from before the webhook was
 * configured. Fire-and-poll: the caller re-fetches listProjectPullRequests
 * to pick up the job's status once it lands, same as everywhere else in this
 * view rather than opening a dedicated stream. */
export function triggerProjectPullRequestReview(
  projectId: number,
  repoId: number,
  prId: number,
): Promise<{ id: string; kind: string; status: string }> {
  return postJSON(`/projects/${projectId}/repos/${repoId}/pull-requests/${prId}/review`, {})
}

export function publishProjectPullRequestReview(
  projectId: number,
  repoId: number,
  prId: number,
): Promise<{ published: boolean; already_published: boolean; published_at: string }> {
  return postJSON(`/projects/${projectId}/repos/${repoId}/pull-requests/${prId}/review/publish`, { confirm: true })
}

// ── Security / VAPT ──────────────────────────────────────────────────────

export function getProjectSecurity(projectId: number): Promise<ProjectSecurity> {
  return getJSON(`/projects/${projectId}/security`)
}

/** Schedules a 'security_scan' job for one repo. Fire-and-poll, same
 * contract as triggerProjectPullRequestReview above. */
export function triggerRepoSecurityScan(
  projectId: number,
  repoId: number,
): Promise<{ id: string; kind: string; status: string }> {
  return postJSON(`/projects/${projectId}/repos/${repoId}/security-scan`, {})
}

/** Schedules a 'pr_security_scan' job — PR Impact Security Analysis, not
 * "scan changed files": the repository-wide impact graph determines scope
 * (see main.py's _stream_pr_security_scan). Fire-and-poll via
 * getRepoPrSecurityScan, same contract as the other trigger/read pairs
 * on this page. */
export function triggerRepoPrSecurityScan(
  projectId: number,
  repoId: number,
  pullRequestId: string | number,
): Promise<{ job_id: string; status: string }> {
  return postJSON(`/projects/${projectId}/repos/${repoId}/security-scan/pr`, { pull_request_id: String(pullRequestId) })
}

export function getRepoPrSecurityScan(
  projectId: number,
  repoId: number,
  jobId: string,
): Promise<PRSecurityScanResult> {
  return getJSON(`/projects/${projectId}/repos/${repoId}/security-scan/pr/${jobId}`)
}

// ── Integrations ─────────────────────────────────────────────────────────

export function getIntegrationsStatus(): Promise<IntegrationsStatus> {
  return getJSON('/integrations/status')
}

// ── Bitbucket ────────────────────────────────────────────────────────────
// Config (BITBUCKET_* env vars) lives server-side — no credentials form
// here, just status + push, mirroring the read-only endpoints in
// app/api/bitbucket.py.

export function getBitbucketRepo(): Promise<BitbucketRepoStatus> {
  return getJSON('/bitbucket/repo')
}

export interface PushToBitbucketRequest {
  generation_id?: number
  output?: GenerationOutput
  epic_id?: string
  /** Target a specific repo when the generation's project has more than
   * one linked repo; omitted uses the project's default repo. */
  repo_id?: number
}

export function pushToBitbucket(req: PushToBitbucketRequest): Promise<BitbucketPushResult> {
  return postJSON('/push-to-bitbucket', req)
}

/** Manually trigger the same code-review agent the Bitbucket webhook
 * triggers automatically on a PR event (app/api/webhooks.py) — useful for
 * re-running a review, or reviewing a PR that predates the webhook being
 * configured. Streams the same finding/done events either way. */
export async function reviewBitbucketPullRequest(
  prId: number | string,
  onEvent: (event: CodeReviewEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const job = await postJSON<BackgroundJob>(`/bitbucket/pull-requests/${prId}/review`, {})
  await pollGenerationJob<CodeReviewEvent>(job.id, onEvent, signal, true, false)
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

// ── Token usage ──────────────────────────────────────────────────────────

export function getUsageSummary(): Promise<UsageSummary> {
  return getJSON('/usage/summary')
}

export function getUsageLog(limit = 100, offset = 0): Promise<{ entries: UsageLogEntry[] }> {
  return getJSON(`/usage/log?limit=${limit}&offset=${offset}`)
}
