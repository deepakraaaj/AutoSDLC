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
  verification?: 'confirmed' | 'risk'
  evidence?: string
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
  // Branch VAPT scans and repo-context reads snapshot; null = the repo's
  // Bitbucket-configured default branch.
  scan_branch: string | null
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
  // Citations backing this section's claims (app/services/wiki_generator.py's
  // grounding validation) — real `path:line` strings, kept separate from
  // `body` (business language only). Not rendered directly; present mainly
  // for completeness/debugging, same audit-trail spirit as artifact_key.
  evidence?: string[]
}

export interface WikiPage {
  id: number
  project_id: number
  repo_id: number | null
  title: string
  summary: string
  sections: WikiPageSection[]
  artifact_key: string | null
  source_revision: string | null
  content_hash: string | null
  generated_at: string
  created_at: string
}

export interface ProjectWiki {
  project_id: number
  pages: WikiPage[]
}

export interface WikiClarificationQuestion {
  id: string
  question: string
  why: string
}

export type WikiGenerationResult =
  | { needs_clarification: false; page: WikiPage }
  | { needs_clarification: true; questions: WikiClarificationQuestion[] }

// ── Multi-chapter wiki (app/services/wiki_chapters.py) ──────────────────
// Additive alongside WikiPage/ProjectWiki above, which stay exactly as they
// are — opt-in per project (ProjectSettings.chapter_wiki_enabled), never a
// replacement. GET /projects/{id}/wiki-chapters returns a FLAT list of
// chapters (parent_id null = top-level); the tree is built client-side the
// same way frontend/src/lib/tree.ts builds TreeEpic/TreeStory/TreeTask.
export interface WikiChapter {
  id: number
  chapter_set_id: number
  parent_id: number | null
  repo_id: number | null
  order_index: number
  title: string | null
  summary: string | null
  sections: WikiPageSection[]
  content_hash: string | null
  generated_at: string | null
}

export interface CrossRepoEdge {
  kind: string
  source_repo_id: number
  target_repo_id: number
  source: string
  target: string
  source_path: string
  source_line: number
  target_path: string
  target_line: number
  method: string
  path_template: string
}

export interface ProjectWikiChapterSet {
  id: number
  project_id: number
  source_revisions: Record<string, string>
  cross_repo_edges: CrossRepoEdge[]
  generated_at: string
  chapters: WikiChapter[]
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
  // Opt-in for the multi-chapter wiki (app/services/wiki_chapters.py) —
  // default false; the flat wiki (ProjectWiki/WikiPage above) stays the
  // default and is never removed even once this is on for a project.
  chapter_wiki_enabled: boolean
}

export interface ProjectSettingsUpdate {
  custom_instructions?: string | null
  chapter_wiki_enabled?: boolean
}

// ── Pull requests ────────────────────────────────────────────────────────
// GET /projects/{id}/pull-requests (app/api/projects.py): PR listings come
// live from Bitbucket, merged with whatever 'bitbucket_review' job last ran
// for each PR — see list_bitbucket_review_jobs in app/services/database.py.

export type PullRequestReviewStatus = 'not_reviewed' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface PullRequestReview {
  status: PullRequestReviewStatus
  job_id: string | null
  error: string | null
  reviewed_at: string | null
  /** Plain-English "what this diff actually changes" (CODE_REVIEW_SYSTEM),
   * not "reviewed the diff" — empty for jobs that ran before this field
   * existed, or if the model ignored the summary instruction. */
  summary: string
  findings_count: number
  severity_counts: { blocking: number; important: number; minor: number }
  /** Full per-finding detail (file/line/severity/comment), not just the
   * count — so a completed review can show what it actually checked and
   * found, not just a bare "Reviewed" badge. */
  findings: CodeReviewFinding[]
  /** The diff's touched files — shown alongside findings (or in place of
   * them, when there are none) so "no issues" reads as "checked these N
   * files, found nothing" rather than an unqualified claim. */
  files_reviewed: string[]
  /** Real per-call usage from the provider's own response (not an
   * estimate) — null for jobs that ran before this field existed, or on a
   * provider that doesn't report usage. */
  token_usage: TokenUsage | null
  /** Server-measured wall-clock time for this review. */
  duration_seconds: number | null
  integrity_check: 'second_pass' | 'no_findings_to_verify' | null
  related_repositories_checked: number
  publication: { job_id: string; comment_id: string | null; published_at: string } | null
}

export interface ProjectPullRequest {
  id: number
  title: string
  author: string | null
  source_branch: string | null
  destination_branch: string | null
  state: string
  created_on: string | null
  updated_on: string | null
  html_url: string | null
  review: PullRequestReview
  /** Latest PR Impact Security Analysis for this PR, if one has ever been
   * run — same shape the security-scan/pr/{jobId} endpoint returns, embedded
   * here so it survives a page refresh. null when never run. */
  security: PRSecurityScanResult | null
}

export interface ProjectRepoPullRequests {
  repo_id: number
  label: string
  repo_full_name: string
  pull_requests: ProjectPullRequest[]
  error: string | null
}

export interface ProjectPullRequests {
  project_id: number
  repos: ProjectRepoPullRequests[]
}

// ── Security / VAPT ──────────────────────────────────────────────────────
// GET /projects/{id}/security (app/api/projects.py): Phase 1 is an LLM
// security pass over each repo's current contents, run as a durable
// 'security_scan' job — see run_security_review in
// app/services/langgraph_pipeline.py.

export type SecurityScanStatus = 'not_scanned' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export type SecurityFindingCategory =
  | 'injection' | 'auth' | 'secrets' | 'ssrf' | 'deserialization'
  | 'path-traversal' | 'crypto' | 'xxe' | 'input-validation' | 'data-exposure'
  | 'dependency' | 'misconfiguration' | 'code' | 'other'

export interface SecurityFinding {
  file: string
  line?: number
  category: SecurityFindingCategory
  severity: 'critical' | 'high' | 'medium' | 'low'
  comment: string
  recommendation?: string
  tool?: string
  rule_id?: string
  identifiers?: string[]
  evidence?: string
  verification?: string
  fingerprint?: string
  /** How many raw advisories are bundled into this one card (same package,
   * different CVEs/GHSAs merged for display — see _security_summary).
   * Absent/1 means no bundling happened. */
  advisory_count?: number
}

export interface RepoSecurityScan {
  status: SecurityScanStatus
  job_id: string | null
  error: string | null
  scanned_at: string | null
  findings: SecurityFinding[]
  severity_counts: { critical: number; high: number; medium: number; low: number }
  tools: { name: string; status: string; findings_count: number; version?: string | null; error?: string | null }[]
  snapshot_files: number
  scanner_commit: string | null
  duration_seconds: number | null
}

export interface ProjectRepoSecurity {
  repo_id: number
  label: string
  repo_full_name: string
  scan: RepoSecurityScan
}

export interface ProjectSecurity {
  project_id: number
  repos: ProjectRepoSecurity[]
}

// ── PR Impact Security Analysis ──────────────────────────────────────────
// POST /projects/{id}/repos/{repoId}/security-scan/pr, GET .../pr/{jobId}
// (app/api/projects.py) — a second scan mode alongside the Full Repository
// Scan above. See main.py's _stream_pr_security_scan and
// app/services/security/ for how a finding gets classified.

export type PRSecurityRelation = 'DIRECT' | 'INDIRECT' | 'DEPENDENCY' | 'EXISTING_RELEVANT' | 'EXISTING_NEWLY_EXPOSED'
export type PRSecurityConfidence = 'HIGH' | 'MEDIUM' | 'LOW'
export type PRSecurityJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface PRSecurityFinding {
  id: number
  fingerprint: string
  source: string | null
  rule_id: string | null
  title: string | null
  description: string | null
  severity: 'critical' | 'high' | 'medium' | 'low'
  confidence: PRSecurityConfidence | null
  file: string | null
  start_line: number | null
  end_line: number | null
  symbol: string | null
  category: string | null
  cwe: string | null
  cve: string | null
  evidence: string | null
  remediation: string | null
  relation_to_pr: PRSecurityRelation
  relation_confidence: PRSecurityConfidence
  affected_path: string[]
  metadata: { baseline_state?: string; reason?: string }
}

export interface PRSecurityBaseline {
  source: 'EXACT_BASE_COMMIT' | 'DESTINATION_BRANCH_LATEST' | 'NONE'
  confidence: PRSecurityConfidence | 'NONE'
  commit_sha: string | null
}

export interface PRSecurityScanResult {
  job_id: string
  status: PRSecurityJobStatus
  error: string | null
  updated_at: string | null
  stages?: { stage: string; status?: string; message?: string }[]
  scan?: { id: number; head_commit_sha: string | null; base_commit_sha: string | null; created_at: string; completed_at: string | null }
  pull_request_id?: string
  /** Plain-English "what did this PR actually do" — always present once
   * the scan succeeds, independent of whether any security finding was
   * reported, so a non-security reader (a manager, a PM) has something to
   * read even on a clean result. */
  summary?: string
  summary_source?: 'llm' | 'fallback'
  changed_files?: number
  changed_symbols?: number
  affected_files?: number
  affected_symbols?: number
  /** What changed_symbols/affected_files above actually count — the stat
   * tiles are just numbers, these are what backs them so the UI can show
   * the real list rather than a bare count with nothing behind it. */
  changed_symbols_detail?: { file: string; symbol: string | null; change_status: string; seed_type: string }[]
  affected_files_detail?: string[]
  context_truncated?: boolean
  graph_truncated?: boolean
  truncation_reasons?: string[]
  llm_review_status?: 'ok' | 'failed' | null
  baseline?: PRSecurityBaseline
  severity_counts?: { critical: number; high: number; medium: number; low: number }
  findings_by_relation?: Partial<Record<PRSecurityRelation, number>>
  findings?: PRSecurityFinding[]
  duration_seconds?: number
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

// ── Token usage log ──────────────────────────────────────────────────────
// GET /usage/summary + /usage/log (app/api/usage.py): every logged row is a
// LiteLLMProvider's own reported usage (app/services/database.py's
// record_token_usage), never an estimate.

export interface UsageWindow {
  ai_calls: number
  total_tokens: number
  cost_usd: number
}

export interface UsageSummary {
  today: UsageWindow
  week: UsageWindow
  month: UsageWindow
  all_time: UsageWindow
}

/** What an AI call was for — mirrors the `kind` strings record_token_usage
 * is called with across the backend. */
export type UsageKind = 'generation' | 'bitbucket_review' | 'security_scan' | 'wiki' | 'repo_brief'

export interface UsageLogEntry {
  id: number
  kind: UsageKind | string
  ref_id: string | null
  provider: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  duration_seconds: number | null
  created_at: string
}
