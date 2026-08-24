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
  /** Bolted on the same way generation_id is (GenerationOutput itself has no notion
   * of a project — it's a DB/history concept) — every 'done' event and /history/{id}
   * carry it so the Backlog view always knows which project it's showing. */
  project_name?: string
  /** Same story as project_name: not part of a generation's own content, attached
   * from the history row (/history/{id} does return it — see HistoryDetail) so
   * BacklogHeader can show when this backlog was created. A live 'done' event has
   * no natural value here (the row doesn't exist until this response saves it), so
   * useGeneration fills in "now" for that case, which is accurate at the moment. */
  created_at?: string
  /** Same story as project_name/created_at above: not part of a generation's
   * own content, bolted on so Overview can show this backlog's project wiki
   * (and know which repos to offer) without a second round trip. null for a
   * generation that was never attached to a project. */
  project_id?: number | null
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
  // `phase` is present only on step-by-step endpoints (/generate-epics,
  // /generate-stories/{id}, /generate-tasks/{id}, /generate-test-cases/{id})
  // — the one-click /generate-stream 'done' event omits it. This is how the
  // client tells a single-phase completion apart from a full run finishing.
  // auto_pushed is set only when this generation's project settings had
  // auto-push-to-Bitbucket on AND the backlog scored 'trusted' at this
  // phase's completion (main.py's _maybe_auto_push_bitbucket) — absent
  // otherwise, not a false/empty value.
  | { type: 'done'; output: GenerationOutput; phase?: 'epics' | 'stories' | 'tasks' | 'tests'; auto_pushed?: BitbucketPushResult }
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
  id: number
  created_at: string
  project_name: string
  project_id: number | null
  input_text: string
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

// ── Bitbucket ────────────────────────────────────────────────────────────
// Unlike Redmine, connection config (BITBUCKET_* env vars) lives server-side
// — there's no URL/API-key form here, just a status the UI reads and a push
// action. See bitbucket/client.py and app/api/bitbucket.py.

export interface BitbucketRepoStatus {
  configured: boolean
  full_name?: string
  workspace?: string
  error?: string
}

export interface BitbucketCreatedIssue {
  type: string
  db_id?: number
  ai_id?: string
  display_id?: string
  bitbucket_id?: string
  url?: string
  status?: 'created' | 'skipped'
  reason?: string
  error?: string
}

export interface BitbucketPushResult {
  created_issues: BitbucketCreatedIssue[]
  skipped_issues?: BitbucketCreatedIssue[]
  warnings?: string[]
}

export interface CodeReviewFinding {
  file: string
  line?: number
  severity: 'blocking' | 'important' | 'minor'
  comment: string
}

/** Events streamed from POST /bitbucket/pull-requests/{id}/review, same SSE
 * framing as StreamEvent above but for run_code_review's own event shapes
 * (app/services/langgraph_pipeline.py) rather than generation's. */
export type CodeReviewEvent =
  | { type: 'status'; message?: string }
  | { type: 'finding'; finding: CodeReviewFinding }
  | { type: 'done'; pr_id: number | string; repo_full_name: string; findings: CodeReviewFinding[] }
  | { type: 'error'; error: AppErrorPayload }

// ── Projects ─────────────────────────────────────────────────────────────
// Project is a first-class entity (app/api/projects.py) — a generation
// optionally belongs to one. A project can hold N repos (frontend,
// backend, ...); settings (instructions, auto-push) are per-project.

export interface ProjectRepo {
  id: number
  label: string | null
  workspace: string
  repo_slug: string
  verified_at: string | null
  created_at: string
}

export interface ProjectListItem {
  id: number
  name: string
  description: string | null
  created_at: string
  ticket_prefix: string | null
  repo_count: number
  generation_count: number
}

export interface ProjectGenerationSummary {
  id: number
  created_at: string
  project_name: string | null
}

export interface ProjectDetail {
  id: number
  name: string
  description: string | null
  created_at: string
  ticket_prefix: string | null
  repos: ProjectRepo[]
  generations: ProjectGenerationSummary[]
}

export type SprintStatus = 'draft' | 'approved' | 'active' | 'completed'

export interface SprintPlan {
  id: number
  project_id: number
  name: string
  objective: string
  start_date: string
  end_date: string
  capacity_hours: number
  story_ids: string[]
  status: SprintStatus
  created_at: string
  updated_at: string
}

export type SprintPlanInput = Omit<SprintPlan, 'id' | 'project_id' | 'created_at' | 'updated_at'>

export interface RepoVerification {
  attempted: boolean
  ok?: boolean
  error?: string
}

export type AddedProjectRepo = ProjectRepo & { verification: RepoVerification }

// ── Wiki ─────────────────────────────────────────────────────────────────
// One AI-generated page for the project itself (repo_id null), plus one per
// linked repo (repo_id set) — see app/services/wiki_generator.py.

export interface WikiPageSection {
  heading: string
  body: string
}

export interface WikiPage {
  id: number
  project_id: number
  repo_id: number | null
  title: string
  summary: string
  sections: WikiPageSection[]
  generated_at: string
  created_at: string
}

export interface ProjectWiki {
  project_id: number
  pages: WikiPage[]
}

// auto_push_bitbucket and default_redmine_project_id still exist on the backend
// (app/schemas/models.py) — auto_push_bitbucket gates a real, tested automation
// (main.py's _maybe_auto_push_bitbucket), so it's deliberately left in place
// there even though its only UI control (the old Push Destinations settings
// section) was removed as redundant/unused. Not modeled here since nothing in
// the frontend reads or writes either field anymore.
export interface ProjectSettings {
  project_id: number
  custom_instructions: string | null
}

export interface ProjectSettingsUpdate {
  custom_instructions?: string | null
}

// ── Integrations ─────────────────────────────────────────────────────────

export interface IntegrationsStatus {
  bitbucket: { connected: boolean; workspace: string | null }
  redmine: { connected: boolean; project_id: string | null }
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
