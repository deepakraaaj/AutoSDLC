import { useState } from 'react'
import type { TreeEpic, TreeStory, TreeTask } from '../../lib/tree'
import { Modal } from '../Modal'
import { PriorityBadge } from './PriorityBadge'
import { StaticStatusBadge } from './StatusBadge'
import { TestCasesPanel } from './TestCasesPanel'
import { DENIED_MESSAGES } from '../../lib/roles'
import { useRole } from '../../hooks/useRole'
import {
  ApiError,
  updateEpicContent,
  updateEpicPriority,
  updateStoryContent,
  updateStoryPriority,
  updateTaskContent,
  updateTaskPriority,
  deleteEpic,
  deleteStory,
  deleteTask,
} from '../../api/client'
import { useToast } from '../../hooks/useToast'
import type { Priority } from '../../types'
import styles from './DetailModal.module.css'

export type DetailTarget =
  | { kind: 'epic'; epic: TreeEpic }
  | { kind: 'story'; epic: TreeEpic; story: TreeStory }
  | { kind: 'task'; epic: TreeEpic; story: TreeStory; task: TreeTask }

const PRIORITY_OPTIONS: Priority[] = ['critical', 'high', 'medium', 'low']

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

/** Textarea <-> string[] — one item per line, blank lines dropped. Used for
 * acceptance criteria and task dependencies, both stored as JSON arrays. */
function linesToList(text: string): string[] {
  return text.split('\n').map((s) => s.trim()).filter(Boolean)
}

export function DetailModal({
  target,
  onClose,
  onPushToRedmine,
  onSaved,
  onCreateChild,
}: {
  target: DetailTarget | null
  onClose: () => void
  onPushToRedmine: (epicId: string, epicTitle: string) => void
  /** Called after a successful content/priority save so the parent can
   * refresh the hierarchy — the same pattern App.tsx already uses for
   * status/assignee changes (withStatusUpdate). */
  onSaved: () => void
  onCreateChild: (target: { kind: 'story'; epic: TreeEpic } | { kind: 'task'; epic: TreeEpic; story: TreeStory }) => void
}) {
  // Called unconditionally even though `target` may make the early return
  // below moot — Rules of Hooks, can't call useRole() after a conditional return.
  const { canPushToRedmine: canPushRole } = useRole()
  if (!target) return null

  const itemKey = target.kind === 'epic' ? target.epic.key : target.kind === 'story' ? target.story.key : target.task.key

  return (
    <DetailModalContent
      key={itemKey}
      target={target}
      onClose={onClose}
      onPushToRedmine={onPushToRedmine}
      onSaved={onSaved}
      onCreateChild={onCreateChild}
      canPushRole={canPushRole}
    />
  )
}

/** Keyed by item identity in DetailModal above — remounts fresh whenever a
 * different item opens, so local edit state below never leaks stale values
 * from whatever was open before. */
function DetailModalContent({
  target,
  onClose,
  onPushToRedmine,
  onSaved,
  onCreateChild,
  canPushRole,
}: {
  target: Exclude<DetailTarget, null>
  onClose: () => void
  onPushToRedmine: (epicId: string, epicTitle: string) => void
  onSaved: () => void
  onCreateChild: (target: { kind: 'story'; epic: TreeEpic } | { kind: 'task'; epic: TreeEpic; story: TreeStory }) => void
  canPushRole: boolean
}) {
  const { showToast } = useToast()
  const { epic } = target
  const item = target.kind === 'epic' ? target.epic : target.kind === 'story' ? target.story : target.task
  const canPush = epic.dbId != null // meaningful only once this generation is actually saved
  const canEdit = item.dbId != null // same requirement — nothing to persist against otherwise
  const redmineIssueUrl = item.redmineId != null ? savedRedmineIssueUrl(item.redmineId) : null

  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  // The values actually displayed — seeded from the item, replaced with
  // whatever was just saved so the read-only view reflects the edit
  // immediately without waiting on the parent's hierarchy to re-fetch.
  const [values, setValues] = useState(() => ({
    title: item.title,
    priority: item.priority as Priority,
    description: target.kind === 'epic' ? target.epic.description : target.kind === 'task' ? target.task.description : '',
    featureArea: target.kind === 'epic' ? target.epic.featureArea : target.kind === 'story' ? target.story.featureArea : '',
    asA: target.kind === 'story' ? target.story.asA : '',
    iWant: target.kind === 'story' ? target.story.iWant : '',
    soThat: target.kind === 'story' ? target.story.soThat : '',
    acceptanceCriteria: target.kind === 'story' ? target.story.acceptanceCriteria : [],
    definitionOfDone: target.kind === 'task' ? target.task.definitionOfDone : '',
    estimateHours: target.kind === 'task' ? target.task.estimateHours : '',
    dependencies: target.kind === 'task' ? target.task.dependencies : [],
  }))
  const [draft, setDraft] = useState(values)

  const breadcrumb =
    target.kind === 'epic'
      ? `Epic ${epic.id}`
      : target.kind === 'story'
        ? `Epic ${epic.id} › Story ${target.story.id}`
        : `Epic ${epic.id} › Story ${target.story.id} › Task ${target.task.id}`

  function startEdit() {
    setDraft(values)
    setEditing(true)
  }

  async function save() {
    if (item.dbId == null) return
    setSaving(true)
    try {
      if (draft.priority !== values.priority) {
        const updatePriority = target.kind === 'epic' ? updateEpicPriority : target.kind === 'story' ? updateStoryPriority : updateTaskPriority
        await updatePriority(item.dbId, draft.priority)
      }
      if (target.kind === 'epic') {
        await updateEpicContent(item.dbId, { title: draft.title, description: draft.description, feature_area: draft.featureArea })
      } else if (target.kind === 'story') {
        await updateStoryContent(item.dbId, {
          title: draft.title,
          as_a: draft.asA,
          i_want: draft.iWant,
          so_that: draft.soThat,
          acceptance_criteria: draft.acceptanceCriteria,
          feature_area: draft.featureArea,
        })
      } else {
        await updateTaskContent(item.dbId, {
          title: draft.title,
          description: draft.description,
          definition_of_done: draft.definitionOfDone,
          estimate_hours: draft.estimateHours,
          dependencies: draft.dependencies,
        })
      }
      setValues(draft)
      setEditing(false)
      onSaved()
      showToast('Saved', `${target.kind === 'epic' ? 'Epic' : target.kind === 'story' ? 'Story' : 'Task'} updated.`, 'info')
    } catch (e) {
      showToast('Error', e instanceof ApiError ? e.message : 'Failed to save changes', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function remove() {
    if (item.dbId == null) return
    const descendants = target.kind === 'epic' ? ' This also deletes its stories and tasks.' : target.kind === 'story' ? ' This also deletes its tasks.' : ''
    if (!window.confirm(`Delete this ${target.kind}?${descendants}`)) return
    setDeleting(true)
    try {
      const removeItem = target.kind === 'epic' ? deleteEpic : target.kind === 'story' ? deleteStory : deleteTask
      await removeItem(item.dbId)
      showToast('Deleted', `${target.kind === 'epic' ? 'Epic' : target.kind === 'story' ? 'Story' : 'Task'} deleted.`, 'info')
      onSaved()
      onClose()
    } catch (e) {
      showToast('Error', e instanceof ApiError ? e.message : 'Failed to delete item', 'error')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={values.title} subheader={breadcrumb}>
      <div className={styles.badges}>
        {editing ? (
          <select
            className="select"
            value={draft.priority}
            onChange={(e) => setDraft({ ...draft, priority: e.target.value as Priority })}
          >
            {PRIORITY_OPTIONS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        ) : (
          <PriorityBadge priority={values.priority} redmineName={item.redminePriorityName} />
        )}
        <StaticStatusBadge status={item.status} />
        {canEdit && !editing && (
          <div className={styles.itemActions}>
            {target.kind !== 'task' && <button className="btn btn-secondary btn-sm" onClick={() => target.kind === 'epic' ? onCreateChild({ kind: 'story', epic }) : onCreateChild({ kind: 'task', epic, story: target.story })}>Add {target.kind === 'epic' ? 'story' : 'task'}</button>}
            <button className="btn btn-secondary btn-sm" onClick={startEdit}>Edit</button>
            <button className={`btn btn-secondary btn-sm ${styles.deleteBtn}`} onClick={() => void remove()} disabled={deleting}>{deleting ? 'Deleting…' : 'Delete'}</button>
          </div>
        )}
      </div>

      {!editing && target.kind === 'epic' && <p className={styles.desc}>{values.description}</p>}
      {!editing && target.kind === 'story' && (
        <p className={styles.desc}>
          <em>{values.asA}</em> → <strong>{values.iWant}</strong>
        </p>
      )}
      {!editing && target.kind === 'task' && (
        <>
          <p className={styles.desc}>{values.description}</p>
          <div className={styles.dodBox}>
            <span className={styles.dodLabel}>Definition of done</span>
            {values.definitionOfDone}
          </div>
          {values.estimateHours && (
            <div className={styles.meta}>
              <strong>Estimate:</strong> {values.estimateHours} hrs
            </div>
          )}
        </>
      )}

      {editing && (
        <div className={styles.editForm}>
          <label className="field-label" htmlFor="edit-title">Title</label>
          <input id="edit-title" className="text-input" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />

          {target.kind === 'epic' && (
            <>
              <label className="field-label" htmlFor="edit-description">Description</label>
              <textarea id="edit-description" className="textarea" rows={4} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              <label className="field-label" htmlFor="edit-feature-area">Feature area</label>
              <input id="edit-feature-area" className="text-input" value={draft.featureArea} onChange={(e) => setDraft({ ...draft, featureArea: e.target.value })} />
            </>
          )}

          {target.kind === 'story' && (
            <>
              <label className="field-label" htmlFor="edit-as-a">As a</label>
              <input id="edit-as-a" className="text-input" value={draft.asA} onChange={(e) => setDraft({ ...draft, asA: e.target.value })} />
              <label className="field-label" htmlFor="edit-i-want">I want</label>
              <input id="edit-i-want" className="text-input" value={draft.iWant} onChange={(e) => setDraft({ ...draft, iWant: e.target.value })} />
              <label className="field-label" htmlFor="edit-so-that">So that</label>
              <input id="edit-so-that" className="text-input" value={draft.soThat} onChange={(e) => setDraft({ ...draft, soThat: e.target.value })} />
              <label className="field-label" htmlFor="edit-ac">Acceptance criteria (one per line)</label>
              <textarea
                id="edit-ac"
                className="textarea"
                rows={5}
                value={draft.acceptanceCriteria.join('\n')}
                onChange={(e) => setDraft({ ...draft, acceptanceCriteria: linesToList(e.target.value) })}
              />
              <label className="field-label" htmlFor="edit-feature-area-story">Feature area</label>
              <input id="edit-feature-area-story" className="text-input" value={draft.featureArea} onChange={(e) => setDraft({ ...draft, featureArea: e.target.value })} />
            </>
          )}

          {target.kind === 'task' && (
            <>
              <label className="field-label" htmlFor="edit-task-description">Description</label>
              <textarea id="edit-task-description" className="textarea" rows={3} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              <label className="field-label" htmlFor="edit-dod">Definition of done</label>
              <textarea id="edit-dod" className="textarea" rows={2} value={draft.definitionOfDone} onChange={(e) => setDraft({ ...draft, definitionOfDone: e.target.value })} />
              <label className="field-label" htmlFor="edit-estimate">Estimate hours</label>
              <input id="edit-estimate" className="text-input" value={draft.estimateHours} onChange={(e) => setDraft({ ...draft, estimateHours: e.target.value })} />
              <label className="field-label" htmlFor="edit-deps">Dependencies (one per line)</label>
              <textarea
                id="edit-deps"
                className="textarea"
                rows={3}
                value={draft.dependencies.join('\n')}
                onChange={(e) => setDraft({ ...draft, dependencies: linesToList(e.target.value) })}
              />
            </>
          )}

          <div className={styles.editActions}>
            <button className="btn btn-secondary btn-sm" onClick={() => setEditing(false)} disabled={saving}>
              Cancel
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => void save()} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}

      {target.kind === 'task' && <TestCasesPanel testCases={target.task.testCases} />}

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
        ) : !canPushRole ? (
          <p className={styles.redmineNote}>{DENIED_MESSAGES.pushToRedmine}</p>
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
