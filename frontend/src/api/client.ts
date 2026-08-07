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
