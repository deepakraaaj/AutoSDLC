import { useEffect, useState } from 'react'
import {
  ApiError,
  getBitbucketRepo,
  pushToBitbucket,
  reviewBitbucketPullRequest,
} from '../../api/client'
import type { BitbucketPushResult, CodeReviewEvent, CodeReviewFinding, GenerationOutput } from '../../types'
import { Modal } from '../Modal'
import styles from './BitbucketModal.module.css'

type StatusKind = 'idle' | 'loading' | 'success' | 'error'
const STATUS_CHIP: Record<StatusKind, string> = {
  idle: 'Waiting',
  loading: 'Connecting',
  success: 'Ready',
  error: 'Needs attention',
}

const SEVERITY_LABEL: Record<CodeReviewFinding['severity'], string> = {
  blocking: 'Blocking',
  important: 'Important',
  minor: 'Minor',
}

export interface BitbucketScope {
  epicId: string
  label: string
}

export function BitbucketModal({
  open,
  onClose,
  output,
  genId,
  scope = null,
  onPushed,
}: {
  open: boolean
  onClose: () => void
  output: GenerationOutput | null
  genId: number | null
  /** Same idea as RedmineModal's scope: push just this epic and everything
   * under it. Requires genId — a scoped push reads the epic branch from the
   * saved generation server-side. */
  scope?: BitbucketScope | null
  onPushed: (result: BitbucketPushResult) => void
}) {
  const [status, setStatus] = useState<{ kind: StatusKind; title: string; message: string }>({
    kind: 'idle',
    title: 'Checking Bitbucket connection',
    message: '',
  })
  const [repoLabel, setRepoLabel] = useState('')
  const [pushing, setPushing] = useState(false)
  const [result, setResult] = useState<BitbucketPushResult | null>(null)

  const [prId, setPrId] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const [reviewMessage, setReviewMessage] = useState('')
  const [findings, setFindings] = useState<CodeReviewFinding[] | null>(null)
  const [reviewError, setReviewError] = useState('')

  useEffect(() => {
    if (!open) return
    setResult(null)
    setFindings(null)
    setReviewError('')
    setReviewMessage('')
    setStatus({ kind: 'loading', title: 'Checking Bitbucket connection', message: '' })
    getBitbucketRepo()
      .then((repo) => {
        if (!repo.configured) {
          setStatus({
            kind: 'error',
            title: 'Bitbucket not configured',
            message: repo.error || 'Set BITBUCKET_BASE_URL, BITBUCKET_WORKSPACE, BITBUCKET_REPO_SLUG, BITBUCKET_ACCESS_TOKEN on the server.',
          })
          return
        }
        setRepoLabel(repo.full_name || '')
        setStatus({ kind: 'success', title: 'Connected', message: repo.full_name ? `Connected to ${repo.full_name}.` : 'Connected.' })
      })
      .catch((e) => {
        const message = e instanceof ApiError ? e.message : 'Failed to reach Bitbucket'
        setStatus({ kind: 'error', title: 'Connection failed', message })
      })
  }, [open])

  const configured = status.kind === 'success'
  const trustPassed = output?.validation?.trust_level === 'trusted'
  const failedTrustChecks = output?.validation?.checks.filter((check) => !check.passed) || []

  async function handlePush() {
    if (!output) {
      setStatus({ kind: 'error', title: 'Nothing to push', message: 'Generate stories and tasks first.' })
      return
    }
    if (scope?.epicId && !genId) {
      setStatus({ kind: 'error', title: 'Cannot push yet', message: 'This generation needs to finish saving before you can push a single epic.' })
      return
    }
    setPushing(true)
    try {
      const res = await pushToBitbucket({
        ...(genId ? { generation_id: genId } : { output }),
        ...(scope?.epicId ? { epic_id: scope.epicId } : {}),
      })
      const createdCount = (res.created_issues || []).filter((i) => !i.error && i.status === 'created').length
      const skippedCount = (res.skipped_issues || []).length
      setStatus({
        kind: 'success',
        title: scope ? `"${scope.label}" pushed` : 'Backlog pushed',
        message: `Created ${createdCount} issue${createdCount === 1 ? '' : 's'} in ${repoLabel}${skippedCount ? `; skipped ${skippedCount} already synced` : ''}.`,
      })
      setResult(res)
      onPushed(res)
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Push failed'
      setStatus({ kind: 'error', title: 'Push failed', message })
    } finally {
      setPushing(false)
    }
  }

  async function handleReview() {
    if (!prId.trim()) return
    setReviewing(true)
    setFindings(null)
    setReviewError('')
    setReviewMessage('Starting review…')
    try {
      const collected: CodeReviewFinding[] = []
      await reviewBitbucketPullRequest(prId.trim(), (event: CodeReviewEvent) => {
        if (event.type === 'status' && event.message) setReviewMessage(event.message)
        if (event.type === 'finding') collected.push(event.finding)
        if (event.type === 'done') setFindings(event.findings)
        if (event.type === 'error') setReviewError(event.error.message)
      })
      setFindings((current) => current ?? collected)
    } catch (e) {
      setReviewError(e instanceof ApiError ? e.message : 'Review failed')
    } finally {
      setReviewing(false)
    }
  }

  if (result) {
    return (
      <Modal open={open} onClose={() => setResult(null)} title="Created issues">
        <div className={styles.resultContent}>
          {(result.warnings || []).length > 0 && (
            <div className={styles.warningBlock}>
              {result.warnings!.map((w, i) => (
                <div key={i}>Warning: {w}</div>
              ))}
            </div>
          )}
          {result.created_issues.map((issue, i) =>
            issue.error ? (
              <div key={i} className={styles.errorLine}>
                Error: {issue.type || 'Issue'}: {issue.error}
              </div>
            ) : (
              <div key={i} className={styles.okLine}>
                <strong>{issue.type}</strong> ({issue.display_id || issue.ai_id || issue.db_id}) →{' '}
                <a href={issue.url || '#'} target="_blank" rel="noreferrer">
                  View issue #{issue.bitbucket_id} in Bitbucket
                </a>
              </div>
            ),
          )}
          {(result.skipped_issues || []).map((issue, i) => (
            <div key={`skipped-${i}`} className={styles.okLine}>
              <strong>{issue.type}</strong> ({issue.ai_id}) — already synced as{' '}
              <a href={issue.url || '#'} target="_blank" rel="noreferrer">
                View issue #{issue.bitbucket_id} in Bitbucket
              </a>
            </div>
          ))}
        </div>
        <div className={styles.actions}>
          <button className="btn btn-primary btn-block" onClick={() => setResult(null)}>
            Done
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Bitbucket"
      subheader={
        scope
          ? `Connect a workspace, pick a repository, push "${scope.label}" and everything under it.`
          : 'Connect a workspace, pick a repository, push the backlog.'
      }
      closeDisabled={pushing}
    >
      <div className={`${styles.statusCard} ${styles[status.kind]}`}>
        <div className={styles.statusChip}>{STATUS_CHIP[status.kind]}</div>
        <div className={styles.statusCopy}>
          <strong>{status.title}</strong>
          <p>{status.message}</p>
        </div>
        {status.kind === 'loading' && <div className={styles.spinner} aria-hidden="true" />}
      </div>

      <section className={styles.section}>
        <h4>Push backlog</h4>
        <div className={`${styles.trustGate} ${trustPassed ? styles.trustPassed : styles.trustBlocked}`}>
          <div>
            <strong>{trustPassed ? 'Automated Trust Gate passed' : 'Automated Trust Gate blocked sync'}</strong>
            <p>
              {trustPassed
                ? 'Coverage, story quality, task quality, gaps, and input quality passed independent validation.'
                : 'This backlog is not safe to publish automatically yet.'}
            </p>
          </div>
          {!trustPassed && failedTrustChecks.length > 0 && (
            <ul>
              {failedTrustChecks.map((check) => (
                <li key={check.label}>{check.label}: {check.value} (needs {check.threshold})</li>
              ))}
            </ul>
          )}
        </div>
        <div className={styles.actions}>
          <button
            className="btn btn-primary"
            disabled={pushing || reviewing || !configured || !output || !trustPassed}
            onClick={() => void handlePush()}
          >
            {pushing && <span className="btn-spinner" />}
            {pushing
              ? 'Pushing to Bitbucket...'
              : scope
                ? `Sync epic: ${scope.label}`
                : trustPassed
                  ? 'Sync entire backlog'
                  : 'Sync blocked by Trust Gate'}
          </button>
        </div>
      </section>

      <section className={styles.section}>
        <h4>Review a pull request</h4>
        <p className="field-hint">
          Runs the same code-review agent the Bitbucket webhook triggers automatically when a PR opens or updates.
        </p>
        <div className={styles.reviewRow}>
          <input
            className="text-input"
            value={prId}
            onChange={(e) => setPrId(e.target.value)}
            placeholder="PR number, e.g. 42"
            disabled={reviewing || !configured}
          />
          <button className="btn btn-secondary" disabled={reviewing || !configured || !prId.trim()} onClick={() => void handleReview()}>
            {reviewing && <span className="btn-spinner" />}
            {reviewing ? 'Reviewing…' : 'Run review'}
          </button>
        </div>
        {reviewing && reviewMessage && <div className="field-hint">{reviewMessage}</div>}
        {reviewError && <div className={styles.errorLine}>{reviewError}</div>}
        {findings && (
          <div className={styles.findingsList}>
            {findings.length === 0 && <div className="field-hint">No findings — nothing worth flagging in this diff.</div>}
            {findings.map((finding, i) => (
              <div key={i} className={`${styles.finding} ${styles[`sev-${finding.severity}`]}`}>
                <span className={styles.findingSeverity}>{SEVERITY_LABEL[finding.severity]}</span>
                <div>
                  <strong>
                    {finding.file}
                    {finding.line ? `:${finding.line}` : ''}
                  </strong>
                  <p>{finding.comment}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className={styles.actions}>
        <button className="btn btn-secondary" disabled={pushing || reviewing} onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  )
}
