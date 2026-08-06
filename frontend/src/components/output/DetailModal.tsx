import type { TreeEpic, TreeStory, TreeTask } from '../../lib/tree'
import { Modal } from '../Modal'
import { PriorityBadge } from './PriorityBadge'
import { StaticStatusBadge } from './StatusBadge'
import { TestCasesPanel } from './TestCasesPanel'
import styles from './DetailModal.module.css'

export type DetailTarget =
  | { kind: 'epic'; epic: TreeEpic }
  | { kind: 'story'; epic: TreeEpic; story: TreeStory }
  | { kind: 'task'; epic: TreeEpic; story: TreeStory; task: TreeTask }

function savedRedmineIssueUrl(issueId: number | string): string | null {
  try {
    const saved = JSON.parse(localStorage.getItem('redmine-config') || '{}')
    if (!saved.url) return null
    const browserBase = String(saved.url)
      .replace('://host.docker.internal', '://localhost')
      .replace(/\/$/, '')
    return `${browserBase}/issues/${issueId}`
  } catch {
    return null
  }
}

export function DetailModal({
  target,
  onClose,
  onPushToRedmine,
}: {
  target: DetailTarget | null
  onClose: () => void
  onPushToRedmine: (epicId: string, epicTitle: string) => void
}) {
  if (!target) return null

  const { epic } = target
  const item = target.kind === 'epic' ? target.epic : target.kind === 'story' ? target.story : target.task
  const canPush = epic.dbId != null // meaningful only once this generation is actually saved
  const redmineIssueUrl = item.redmineId != null ? savedRedmineIssueUrl(item.redmineId) : null

  const breadcrumb =
    target.kind === 'epic'
      ? `Epic ${epic.id}`
      : target.kind === 'story'
        ? `Epic ${epic.id} › Story ${target.story.id}`
        : `Epic ${epic.id} › Story ${target.story.id} › Task ${target.task.id}`

  return (
    <Modal open onClose={onClose} title={item.title} subheader={breadcrumb}>
      <div className={styles.badges}>
        <PriorityBadge priority={item.priority} redmineName={item.redminePriorityName} />
        <StaticStatusBadge status={item.status} />
      </div>

      {target.kind === 'epic' && <p className={styles.desc}>{target.epic.description}</p>}

      {target.kind === 'story' && (
        <>
          <p className={styles.desc}>
            <em>{target.story.asA}</em> → <strong>{target.story.iWant}</strong>
          </p>
        </>
      )}

      {target.kind === 'task' && (
        <>
          <p className={styles.desc}>{target.task.description}</p>
          <div className={styles.dodBox}>
            <span className={styles.dodLabel}>Definition of done</span>
            {target.task.definitionOfDone}
          </div>
          {target.task.estimateHours && (
            <div className={styles.meta}>
              <strong>Estimate:</strong> {target.task.estimateHours} hrs
            </div>
          )}
          <TestCasesPanel testCases={target.task.testCases} />
        </>
      )}

      <div className={styles.redmineSection}>
        {item.redmineId != null ? (
          <div className={styles.redmineDone}>
            ✓ Already in Redmine —{' '}
            {redmineIssueUrl ? (
              <a href={redmineIssueUrl} target="_blank" rel="noreferrer">
                View Issue #{item.redmineId} in Redmine ↗
              </a>
            ) : (
              `Issue #${item.redmineId}`
            )}
          </div>
        ) : canPush ? (
          <>
            <button className="btn btn-primary" onClick={() => onPushToRedmine(epic.id, epic.title)}>
              Push to Redmine
            </button>
            {target.kind !== 'epic' && (
              <p className={styles.redmineNote}>
                Pushes "{epic.title}" and everything under it, so the Redmine hierarchy stays consistent — not
                just this {target.kind} on its own.
              </p>
            )}
          </>
        ) : (
          <p className={styles.redmineNote}>This generation needs to finish saving before you can push to Redmine.</p>
        )}
      </div>
    </Modal>
  )
}
