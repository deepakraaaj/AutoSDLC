import { useEffect, useState, type CSSProperties } from 'react'
import { ChevronDown, ExternalLink, GitBranch, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { ApiError, listProjectPullRequests, triggerProjectPullRequestReview } from '../../api/client'
import type { ProjectDetail, ProjectPullRequest, ProjectPullRequests, ProjectRepoPullRequests } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { APP_ICONS } from '../icons/appIcons'
import { formatRelative } from '../../lib/format'
import styles from './PullRequestsView.module.css'

// Same fixed palette as Sidebar.tsx's project avatars — deterministic per
// author name so the same person gets the same color across the app.
const AVATAR_COLORS = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d']
function avatarColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) >>> 0
  return AVATAR_COLORS[hash % AVATAR_COLORS.length]
}

// Deterministic per repo_id (not name — a repo can be renamed, its id can't)
// so every card from the same repo carries the same timeline color, telling
// repos apart at a glance once a project has more than one linked.
function repoColor(repoId: number): string {
  return AVATAR_COLORS[repoId % AVATAR_COLORS.length]
}

const REVIEW_LABEL: Record<ProjectPullRequest['review']['status'], string> = {
  not_reviewed: 'Not reviewed',
  queued: 'Review queued',
  running: 'Reviewing…',
  succeeded: 'Reviewed',
  failed: 'Review failed',
  cancelled: 'Review cancelled',
}

function reviewBadgeClass(pr: ProjectPullRequest): string {
  const { status, severity_counts } = pr.review
  if (status === 'failed') return 'badge badge-danger'
  if (status === 'queued' || status === 'running') return 'badge badge-info'
  if (status === 'succeeded') return severity_counts.blocking > 0 ? 'badge badge-danger' : severity_counts.important > 0 ? 'badge badge-warning' : 'badge badge-success'
  return 'badge badge-neutral'
}

function findingBadgeClass(severity: string): string {
  if (severity === 'blocking') return 'badge badge-danger'
  if (severity === 'important') return 'badge badge-warning'
  return 'badge badge-neutral'
}

// Bitbucket's own state vocabulary (OPEN/MERGED/DECLINED/SUPERSEDED) — kept
// as-is rather than remapped, so a PR's state here always matches what
// Bitbucket itself would show.
type PullRequestState = 'OPEN' | 'MERGED' | 'DECLINED' | 'SUPERSEDED'
const STATE_LABEL: Record<string, string> = { OPEN: 'Open', MERGED: 'Merged', DECLINED: 'Declined', SUPERSEDED: 'Superseded' }
function stateBadgeClass(state: string): string {
  if (state === 'MERGED') return 'badge badge-success'
  if (state === 'DECLINED') return 'badge badge-danger'
  if (state === 'SUPERSEDED') return 'badge badge-neutral'
  return 'badge badge-info'
}

const STATE_FILTERS: { id: 'all' | PullRequestState; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'OPEN', label: 'Open' },
  { id: 'MERGED', label: 'Merged' },
  { id: 'DECLINED', label: 'Declined' },
]

/** One card per PR in one repo, with the AI review's outcome — or a "Run
 * review" action when none has run yet. Findings come from the same
 * 'bitbucket_review' job the webhook (app/api/webhooks.py) schedules
 * automatically; this view is read/trigger only, the review itself already
 * posts its findings as PR comments on Bitbucket.
 *
 * Rendered inside a timeline row — a colored dot per PR connected by a line
 * down the repo's whole list, rather than a stripe on each individual card —
 * so repos are told apart by their line/dot color at a glance. */
function PullRequestCard({ projectId, repo, pr, isLast, onReviewTriggered }: { projectId: number; repo: ProjectRepoPullRequests; pr: ProjectPullRequest; isLast: boolean; onReviewTriggered: () => void }) {
  const [triggering, setTriggering] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const { showToast } = useToast()
  const { review } = pr
  const canRunReview = review.status !== 'queued' && review.status !== 'running'
  // Anything with a completed pass (clean or not) has something to show —
  // the actual findings, or an explicit "checked, nothing found" statement.
  // "Reviewed" alone as a bare badge with no way to see what that meant was
  // exactly the complaint this expands to answer.
  const canExpand = review.status === 'succeeded'

  async function runReview() {
    setTriggering(true)
    try {
      await triggerProjectPullRequestReview(projectId, repo.repo_id, pr.id)
      showToast('Review started', `Reviewing PR #${pr.id} — findings post as PR comments when done.`, 'info')
      onReviewTriggered()
    } catch (e) {
      showToast('Failed to start review', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className={styles.timelineRow}>
      <div className={styles.timelineRail}>
        <span className={styles.timelineDot} aria-hidden="true" />
        {!isLast && <span className={styles.timelineLine} aria-hidden="true" />}
      </div>
      <article className={styles.card}>
        <div className={styles.cardTop}>
          <span className={styles.prId}>#{pr.id}</span>
          <span className={stateBadgeClass(pr.state)}>{STATE_LABEL[pr.state] || pr.state}</span>
          {pr.html_url ? (
            <a className={styles.cardTitleLink} href={pr.html_url} target="_blank" rel="noreferrer">
              {pr.title}
            </a>
          ) : (
            <strong className={styles.cardTitlePlain}>{pr.title}</strong>
          )}
          {pr.html_url && (
            <a className={styles.openLink} href={pr.html_url} target="_blank" rel="noreferrer" title="Open on Bitbucket">
              <ExternalLink aria-hidden="true" />
            </a>
          )}
        </div>
        {pr.source_branch && pr.destination_branch && (
          <div className={styles.branches}>
            <code>{pr.source_branch}</code>
            <GitBranch aria-hidden="true" />
            <code>{pr.destination_branch}</code>
          </div>
        )}
        <div className={styles.cardMeta}>
          {pr.author && (
            <span className={styles.authorChip}>
              <span className={styles.authorAvatar} style={{ background: avatarColor(pr.author) }} aria-hidden="true">
                {pr.author.charAt(0).toUpperCase()}
              </span>
              {pr.author}
            </span>
          )}
          {pr.updated_on && <span className={styles.updatedAt}>Updated {formatRelative(pr.updated_on) || new Date(pr.updated_on).toLocaleDateString()}</span>}
        </div>
        <div className={styles.cardFooter}>
          <div className={styles.reviewStatus}>
            <button
              type="button"
              className={`${styles.reviewToggle} ${!canExpand ? styles.reviewToggleStatic : ''}`}
              onClick={() => canExpand && setExpanded((v) => !v)}
              aria-expanded={canExpand ? expanded : undefined}
              disabled={!canExpand}
            >
              <span className={reviewBadgeClass(pr)}>{REVIEW_LABEL[review.status]}</span>
              {canExpand && <ChevronDown aria-hidden="true" className={expanded ? styles.chevronOpen : ''} />}
            </button>
            {review.findings_count > 0 && (
              <span className={styles.findingsSummary}>
                {review.severity_counts.blocking > 0 && <span className={styles.sevBlocking}>{review.severity_counts.blocking} blocking</span>}
                {review.severity_counts.important > 0 && <span className={styles.sevImportant}>{review.severity_counts.important} important</span>}
                {review.severity_counts.minor > 0 && <span className={styles.sevMinor}>{review.severity_counts.minor} minor</span>}
              </span>
            )}
            {review.status === 'failed' && review.error && <span className={styles.reviewError}>{review.error}</span>}
          </div>
          <button className="btn btn-ghost btn-sm" disabled={!canRunReview || triggering} onClick={() => void runReview()}>
            {triggering ? <span className="btn-spinner" /> : <RefreshCw aria-hidden="true" />}
            {review.status === 'not_reviewed' ? 'Run review' : 'Re-run review'}
          </button>
        </div>

        {expanded && canExpand && (
          <div className={styles.reviewDetail}>
            {review.summary && <p className={styles.changeSummary}>{review.summary}</p>}
            <p className={styles.reviewScope}>
              Reviewed{review.reviewed_at ? ` ${formatRelative(review.reviewed_at) || new Date(review.reviewed_at).toLocaleDateString()}` : ''} —{' '}
              {review.files_reviewed.length > 0 ? `${review.files_reviewed.length} file${review.files_reviewed.length === 1 ? '' : 's'} in this diff` : 'this diff'}, checked for correctness bugs, security issues, and missing error handling.
            </p>
            {review.files_reviewed.length > 0 && (
              <div className={styles.filesReviewed}>
                {review.files_reviewed.map((file) => (
                  <code key={file}>{file}</code>
                ))}
              </div>
            )}
            {review.findings.length === 0 ? (
              <div className={styles.reviewClean}>
                <ShieldCheck aria-hidden="true" />
                <span>No issues flagged. An LLM pass over the diff; it can miss things a human review wouldn't, and doesn't replace one.</span>
              </div>
            ) : (
              <ul className={styles.findingList}>
                {review.findings.map((finding, i) => (
                  <li key={i} className={styles.findingRow}>
                    <span className={findingBadgeClass(finding.severity)}>{finding.severity}</span>
                    <div>
                      <code className={styles.findingLocation}>{finding.file}{finding.line ? `:${finding.line}` : ''}</code>
                      <p>{finding.comment}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </article>
    </div>
  )
}

function matchesSearch(pr: ProjectPullRequest, repo: ProjectRepoPullRequests, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return (
    pr.title.toLowerCase().includes(q) ||
    (pr.author || '').toLowerCase().includes(q) ||
    (pr.source_branch || '').toLowerCase().includes(q) ||
    (pr.destination_branch || '').toLowerCase().includes(q) ||
    repo.repo_full_name.toLowerCase().includes(q) ||
    repo.label.toLowerCase().includes(q) ||
    String(pr.id).includes(q)
  )
}

export function PullRequestsView({ project }: { project: ProjectDetail }) {
  const [data, setData] = useState<ProjectPullRequests | null>(null)
  const [stateFilter, setStateFilter] = useState<'all' | PullRequestState>('OPEN')
  const [query, setQuery] = useState('')
  const { showToast } = useToast()

  async function load() {
    try {
      setData(await listProjectPullRequests(project.id))
    } catch (e) {
      showToast('Failed to load pull requests', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  // Self-rescheduling poll while any review is still in flight — a real
  // review takes single-digit seconds (backend job, not a webhook we'd
  // otherwise wait on), but nothing was re-fetching after triggering one,
  // so "Reviewing…" only ever updated if you happened to hit Refresh
  // yourself. Re-checks after each load(); stops scheduling once nothing's
  // queued/running, so it doesn't poll forever once everything's settled.
  useEffect(() => {
    if (!data) return
    const hasPending = data.repos.some((r) => r.pull_requests.some((pr) => pr.review.status === 'queued' || pr.review.status === 'running'))
    if (!hasPending) return
    const timer = setTimeout(() => void load(), 3000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  if (project.repos.length === 0) {
    return (
      <section className={styles.page}>
        <header className={styles.header}>
          <div><h2>Pull requests</h2><p>AI-reviewed pull requests across this project's repos.</p></div>
        </header>
        <div className={`card ${styles.emptyState}`}>
          <p>No repos linked to {project.name} yet</p>
          <p className="text-muted">Link a Bitbucket repo in Project settings to see its pull requests here.</p>
        </div>
      </section>
    )
  }

  if (data === null) {
    return (
      <section className={styles.page} aria-busy="true">
        <header className={styles.header}>
          <div><h2>Pull requests</h2><p>AI-reviewed pull requests across this project's repos.</p></div>
        </header>
        <SkeletonList rows={3} />
      </section>
    )
  }

  const totalAll = data.repos.reduce((n, r) => n + r.pull_requests.length, 0)
  // Plain recompute each render, not useMemo — this runs after two
  // conditional early returns above (data === null, no repos), so a hook
  // here would violate the Rules of Hooks (conditionally-called hook). The
  // list is small enough that memoizing it would only add risk for no
  // measurable benefit.
  const visibleRepos = data.repos.map((repo) => ({
    ...repo,
    pull_requests: repo.pull_requests
      .filter((pr) => stateFilter === 'all' || pr.state === stateFilter)
      .filter((pr) => matchesSearch(pr, repo, query)),
  }))
  const totalVisible = visibleRepos.reduce((n, r) => n + r.pull_requests.length, 0)

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div><h2>Pull requests</h2><p>AI-reviewed pull requests across this project's repos.</p></div>
        <button className="btn btn-secondary btn-sm" onClick={() => void load()}>
          <RefreshCw aria-hidden="true" /> Refresh
        </button>
      </header>

      {totalAll > 0 && (
        <div className={styles.toolbar}>
          <div className={styles.stateTabs} role="tablist" aria-label="Filter by pull request state">
            {STATE_FILTERS.map((f) => (
              <button
                key={f.id}
                role="tab"
                aria-selected={stateFilter === f.id}
                className={stateFilter === f.id ? styles.stateTabActive : ''}
                onClick={() => setStateFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className={styles.searchBox}>
            <Search aria-hidden="true" />
            <input
              type="search"
              placeholder="Search title, author, branch…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search pull requests"
            />
          </label>
        </div>
      )}

      {totalAll === 0 && data.repos.every((r) => !r.error) && (
        <div className={`card ${styles.emptyState}`}>
          <APP_ICONS.pullRequests aria-hidden="true" />
          <p>No pull requests yet</p>
          <p className="text-muted">New PRs on a linked repo trigger a review automatically once the Bitbucket webhook is configured.</p>
        </div>
      )}

      {totalAll > 0 && totalVisible === 0 && (
        <div className={`card ${styles.emptyState}`}>
          <p>{query.trim() ? 'No pull requests match your search' : `No ${STATE_FILTERS.find((f) => f.id === stateFilter)?.label.toLowerCase()} pull requests`}</p>
          <p className="text-muted">{query.trim() ? 'Try a different search term.' : 'Try a different filter above.'}</p>
        </div>
      )}

      {visibleRepos.map((repo) => {
        if (repo.pull_requests.length === 0 && !repo.error) return null
        return (
          <div key={repo.repo_id} className={styles.repoSection}>
            <div className={styles.repoHeading}>
              <span className={styles.repoDot} style={{ background: repoColor(repo.repo_id) }} aria-hidden="true" />
              <GitBranch aria-hidden="true" />
              <strong>{repo.label}</strong>
              <span>{repo.repo_full_name}</span>
            </div>
            {repo.error ? (
              <div className={styles.repoError}>{repo.error}</div>
            ) : (
              <div className={styles.timelineList} style={{ '--repo-stripe': repoColor(repo.repo_id) } as CSSProperties}>
                {repo.pull_requests.map((pr, i) => (
                  <PullRequestCard
                    key={pr.id}
                    projectId={project.id}
                    repo={repo}
                    pr={pr}
                    isLast={i === repo.pull_requests.length - 1}
                    onReviewTriggered={() => void load()}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </section>
  )
}
