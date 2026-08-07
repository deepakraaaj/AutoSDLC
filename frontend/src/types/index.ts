/**
 * Mirrors app/schemas/models.py. Keep in sync with the backend by hand —
 * there's no shared schema generation in this repo, so a field renamed on
 * one side and not the other will only surface at runtime. If that becomes
 * a recurring problem, generating this from the FastAPI OpenAPI schema
 * would be the next step.
 */

export type Priority = 'critical' | 'high' | 'medium' | 'low'
export type Confidence = 'high' | 'medium' | 'low'
export type Size = 'small' | 'medium' | 'large'
export type EpicStatus = 'planned' | 'in-progress' | 'done'
export type StoryStatus = 'planned' | 'in-progress' | 'review' | 'done'
export type TaskStatus = 'todo' | 'in-progress' | 'testing' | 'done'
export type Severity = 'blocking' | 'important' | 'minor'
export type TestType = 'functional' | 'edge_case' | 'negative' | 'regression'
export type TrustLevel = 'trusted' | 'review' | 'low'
export type InputQuality = 'high' | 'medium' | 'low'

export interface Epic {
  id: string
  title: string
  description: string
  feature_area: string
  priority: Priority
  status: EpicStatus
}

export interface Story {
  id: string
  title: string
  as_a: string
  i_want: string
  so_that: string
  acceptance_criteria: string[]
  feature_area: string
  size: Size
  confidence: Confidence
  epic_id: string | null
  priority: Priority
  status: StoryStatus
}

/** A manual QA test case — deliberately not code. Meant for a QA tester to
 * execute by hand or attach to a Redmine issue, not a source-code test suite. */
export interface TestCase {
  id: string
  title: string
  test_type: TestType
  description: string
  preconditions: string
  steps: string[]
  expected_result: string
}

export interface Task {
  id: string
  title: string
  description: string
  definition_of_done: string
  estimate_hours: string
  dependencies: string[]
  test_cases: TestCase[]
  story_id: string | null
  confidence: Confidence
  priority: Priority
  status: TaskStatus
  assignee: string | null
}

export interface Gap {
  description: string
  severity: Severity
}

export interface ClarifyingQuestion {
  question: string
  why_it_matters: string
}

export interface StoryMetrics {
  specificity_score: number
  testability_score: number
  sizing_score: number
  edge_case_score: number
  overall: number
}

export interface TaskMetrics {
  clarity_score: number
  definition_of_done_score: number
  estimate_score: number
  dependency_score: number
  overall: number
}

export interface TestMetrics {
  coverage_score: number
  expected_result_quality_score: number
  edge_case_coverage_score: number
  overall: number
}

export interface TokenUsage {
  ai_calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
}

export interface OverallMetrics {
  coverage_score: number
  gap_count: number
  input_quality: InputQuality
  story_metrics: StoryMetrics
  task_metrics: TaskMetrics
  test_metrics: TestMetrics | null
  confidence_summary: string
  /** Wall-clock seconds this generation actually took, measured server-side.
   * Null for older generations saved before this was tracked. */
  generation_seconds: number | null
  /** Null for the rule-based compiler path (no AI calls) or older
   * generations saved before this was tracked. */
  token_usage: TokenUsage | null
}

export interface ValidationCheck {
  label: string
  passed: boolean
  value: string
  threshold: string
}

export interface ValidationResult {
  trust_level: TrustLevel
  checks: ValidationCheck[]
  recommendation: string
}

export interface GenerationOutput {
  needs_clarification: boolean
  clarifying_questions: ClarifyingQuestion[]
  epics: Epic[]
  stories: Story[]
  tasks: Task[]
  gaps: Gap[]
  metrics: OverallMetrics | null
  validation: ValidationResult | null
  generation_id?: number
}

// ── Hierarchy (as returned by /hierarchy/{id} — DB-backed, has db_id/redmine_id) ──

export interface HierarchyTask extends Omit<Task, 'test_cases'> {
  db_id: number
  ai_id?: string
  issue_id?: string
  redmine_id?: number | string | null
  redmine_priority_name?: string | null
  test_cases: TestCase[]
}

export interface HierarchyStory extends Omit<Story, 'status'> {
  db_id: number
  ai_id?: string
  issue_id?: string
  status: StoryStatus
  redmine_id?: number | string | null
  redmine_priority_name?: string | null
  tasks: HierarchyTask[]
}

export interface HierarchyEpic extends Omit<Epic, 'status'> {
  db_id: number
  ai_id?: string
  issue_id?: string
  status: EpicStatus
  redmine_id?: number | string | null
  redmine_priority_name?: string | null
  stories: HierarchyStory[]
}

export interface Hierarchy {
  epics: HierarchyEpic[]
}

// ── SSE stream events (main.py's _sse()/error yields) ──────────────────────

export interface AppErrorPayload {
  code: string
  message: string
  severity: 'info' | 'warning' | 'error' | 'critical'
  details: string | null
  userAction: string | null
  timestamp: string
}

export type StreamEvent =
  | { type: 'status'; step?: string; message?: string }
  | { type: 'input'; text: string }
  | { type: 'token'; text: string }
  // Emitted as each item is generated — Phase 1/2/3 send these live so the
  // UI can build the backlog on screen as it happens instead of showing a
  // blank progress bar until everything finishes. Phase 4 re-sends a task
  // event once test cases land on it (same id, upsert not append).
  | { type: 'epic'; epic: Epic }
  | { type: 'story'; story: Story }
  | { type: 'task'; task: Task }
  | { type: 'done'; output: GenerationOutput }
  | { type: 'warning'; message: string }
  | { type: 'error'; error: AppErrorPayload }

// ── History ──────────────────────────────────────────────────────────────

export interface HistoryListItem {
  id: number
  created_at: string
  project_name: string
  metrics: OverallMetrics | null
}

export interface HistoryDetail {
  output: GenerationOutput
}

// ── Dashboard ────────────────────────────────────────────────────────────

export interface DashboardStats {
  total_epics: number
  total_stories: number
  total_tasks: number
  epic_status: Record<string, number>
  story_status: Record<string, number>
  task_status: Record<string, number>
  unassigned_tasks: number
}

// ── Redmine ──────────────────────────────────────────────────────────────

export interface RedmineProjectOption {
  value: string
  label: string
  path: string
  depth: number
  id: number
  name: string
  identifier: string
  parent_id: number | null
  parent_identifier: string | null
  parent_name: string | null
}

export interface RedmineDefaults {
  required_trackers: string[]
  missing_trackers: string[]
  required_custom_fields: string[]
  missing_custom_fields: string[]
  missing_tracker_defaults: string[]
}

export interface RedmineWorkspace {
  projects: unknown[]
  project_options: RedmineProjectOption[]
  trackers: unknown[]
  custom_fields: unknown[]
  defaults: RedmineDefaults
}

export interface RedmineCreatedIssue {
  type: string
  db_id?: number
  ai_id?: string
  display_id?: string
  redmine_id?: number
  url?: string
  redmine_priority_name?: string
  status?: 'created' | 'skipped'
  reason?: string
  error?: string
}

export interface RedminePushResult {
  created_issues: RedmineCreatedIssue[]
  skipped_issues?: RedmineCreatedIssue[]
  warnings?: string[]
}

// ── Assistant chat ───────────────────────────────────────────────────────

export interface AssistantIssue {
  id: number
  subject: string
  status: string | null
  priority: string | null
  assignee: string | null
  tracker: string | null
  project: string | null
  project_id: number | null
  updated_on: string | null
  url: string | null
  description?: string
}

export interface AssistantPendingAction {
  intent: string
  params: Record<string, unknown>
}

export interface AssistantChatResponse {
  reply: string
  action: 'none' | 'trigger_generation' | 'trigger_push'
  generation_text?: string
  issues?: AssistantIssue[]
  issue?: AssistantIssue
  requires_confirmation: boolean
  pending_action?: AssistantPendingAction
  warnings?: string[]
}

// ── Misc ─────────────────────────────────────────────────────────────────

export interface BriefValidation {
  word_count: number
  score: 'strong' | 'moderate' | 'vague'
  suggestions: string[]
}

export interface TokenEstimate {
  word_count: number
  estimated_calls: number
  estimated_time_seconds: number
  cost_usd: number
}

export interface BriefResources {
  resources: Record<string, string>
}

export type ToastSeverity = 'info' | 'warning' | 'error' | 'critical'

// ── AI provider settings ────────────────────────────────────────────────

export interface ProviderUsageMeter {
  used: number
  limit: number
  window: 'minute' | 'day' | 'current'
}

export interface ProviderUsage {
  requests: ProviderUsageMeter
  tokens?: ProviderUsageMeter
  last_error: string | null
  /** True once a real probe (see /providers/refresh) has populated these
   * numbers from the provider's own response headers — false means these
   * are just this app's own tracked usage since it last restarted, which
   * can read far lower than the account's real state. */
  live: boolean
  checked_at: string | null
  /** True when a live check succeeded but the provider (Gemini) doesn't
   * expose numeric quota headers on success — the requests/tokens meters
   * above are still just the self-tracked estimate in that case. */
  no_live_numbers?: boolean
}

export interface ProviderInfo {
  id: string
  label: string
  model: string
  configured: boolean
  active: boolean
  usage: ProviderUsage
}

export interface ProviderList {
  active: string
  providers: ProviderInfo[]
}
