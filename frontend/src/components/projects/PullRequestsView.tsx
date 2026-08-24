import { useEffect, useState } from 'react'
import { ExternalLink, GitBranch, RefreshCw } from 'lucide-react'
import { ApiError, listProjectPullRequests, triggerProjectPullRequestReview } from '../../api/client'
import type { ProjectDetail, ProjectPullRequest, ProjectPullRequests, ProjectRepoPullRequests } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { APP_ICONS } from '../icons/appIcons'
import styles from './PullRequestsView.module.css'

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

/** One card per open PR in one repo, with the AI review's outcome — or a
 * "Run review" action when none has run yet. Findings come from the same
 * 'bitbucket_review' job the webhook (app/api/webhooks.py) schedules
 * automatically; this view is read/trigger only, the review itself already
 * posts its findings as PR comments on Bitbucket. */
function PullRequestCard({ projectId, repo, pr, onReviewTriggered }: { projectId: number; repo: ProjectRepoPullRequests; pr: ProjectPullRequest; onReviewTriggered: () => void }) {
  const [triggering, setTriggering] = useState(false)
  const { showToast } = useToast()
  const { review } = pr
  const canRunReview = review.status !== 'queued' && review.status !== 'running'

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
    <article className={styles.card}>
      <div className={styles.cardTop}>
        <div className={styles.cardTitle}>
          <span className={styles.prId}>#{pr.id}</span>
          <strong>{pr.title}</strong>
        </div>
        {pr.html_url && (
          <a className={styles.openLink} href={pr.html_url} target="_blank" rel="noreferrer" title="Open on Bitbucket">
            <ExternalLink aria-hidden="true" />
          </a>
        )}
      </div>
      <div className={styles.cardMeta}>
        {pr.author && <span>{pr.author}</span>}
        {pr.source_branch && pr.destination_branch && (
          <span className={styles.branches}><GitBranch aria-hidden="true" />{pr.source_branch} → {pr.destination_branch}</span>
        )}
        {pr.updated_on && <span>Updated {new Date(pr.updated_on).toLocaleDateString()}</span>}
      </div>
      <div className={styles.cardFooter}>
        <div className={styles.reviewStatus}>
          <span className={reviewBadgeClass(pr)}>{REVIEW_LABEL[review.status]}</span>
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
    </article>
  )
}

export function PullRequestsView({ project }: { project: ProjectDetail }) {
  const [data, setData] = useState<ProjectPullRequests | null>(null)
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

  if (project.repos.length === 0) {
    return (
      <section className={styles.page}>
        <header className={styles.header}>
          <div><h2>Pull requests</h2><p>AI-reviewed pull requests across this project's repos.</p></div>
        </header>
        <div className={`card ${styles.emptyState}`}>
          <p>No repos linked to {project.name} yet</p>
          <p className="text-muted">Link a Bitbucket repo in Project settings to see its open pull requests here.</p>
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

  const totalOpen = data.repos.reduce((n, r) => n + r.pull_requests.length, 0)

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div><h2>Pull requests</h2><p>AI-reviewed pull requests across this project's repos.</p></div>
        <button className="btn btn-secondary btn-sm" onClick={() => void load()}>
          <RefreshCw aria-hidden="true" /> Refresh
        </button>
      </header>

      {totalOpen === 0 && data.repos.every((r) => !r.error) && (
        <div className={`card ${styles.emptyState}`}>
          <APP_ICONS.pullRequests aria-hidden="true" />
          <p>No open pull requests</p>
          <p className="text-muted">New PRs on a linked repo trigger a review automatically once the Bitbucket webhook is configured.</p>
        </div>
      )}

      {data.repos.map((repo) => (
        <div key={repo.repo_id} className={styles.repoSection}>
          <div className={styles.repoHeading}>
            <GitBranch aria-hidden="true" />
            <strong>{repo.label}</strong>
            <span>{repo.repo_full_name}</span>
          </div>
          {repo.error ? (
            <div className={styles.repoError}>{repo.error}</div>
          ) : repo.pull_requests.length === 0 ? (
            <p className={styles.repoEmpty}>No open pull requests.</p>
          ) : (
            <div className={styles.cardList}>
              {repo.pull_requests.map((pr) => (
                <PullRequestCard key={pr.id} projectId={project.id} repo={repo} pr={pr} onReviewTriggered={() => void load()} />
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
