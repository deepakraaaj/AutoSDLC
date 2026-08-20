import { useState } from 'react'
import { Modal } from '../Modal'
import { ApiError, createEpic, createStory, createTask } from '../../api/client'
import type { TreeEpic, TreeStory } from '../../lib/tree'
import { useToast } from '../../hooks/useToast'
import styles from './DetailModal.module.css'

export type CreateTarget =
  | { kind: 'epic'; generationId: number }
  | { kind: 'story'; epic: TreeEpic }
  | { kind: 'task'; epic: TreeEpic; story: TreeStory }

export function CreateItemModal({ target, onClose, onCreated }: {
  target: CreateTarget | null
  onClose: () => void
  onCreated: () => void
}) {
  const { showToast } = useToast()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [asA, setAsA] = useState('User')
  const [iWant, setIWant] = useState('')
  const [soThat, setSoThat] = useState('')
  const [featureArea, setFeatureArea] = useState('General')
  const [saving, setSaving] = useState(false)

  if (!target) return null
  // Capture the narrowed value so TypeScript keeps the discriminated union
  // intact inside the async save callback as well.
  const createTarget = target
  const label = createTarget.kind === 'epic' ? 'Epic' : createTarget.kind === 'story' ? 'Story' : 'Task'

  async function save() {
    if (!title.trim()) return
    setSaving(true)
    try {
      if (createTarget.kind === 'epic') {
        await createEpic({ generation_id: createTarget.generationId, title: title.trim(), description, feature_area: featureArea })
      } else if (createTarget.kind === 'story') {
        if (createTarget.epic.dbId == null) return
        await createStory({ epic_id: createTarget.epic.dbId, title: title.trim(), as_a: asA, i_want: iWant, so_that: soThat, acceptance_criteria: [], feature_area: featureArea })
      } else {
        if (createTarget.story.dbId == null) return
        await createTask({ story_id: createTarget.story.dbId, title: title.trim(), description, definition_of_done: '', estimate_hours: '', dependencies: [] })
      }
      showToast('Created', `${label} added to the backlog.`, 'info')
      onCreated()
      onClose()
    } catch (e) {
      showToast('Error', e instanceof ApiError ? e.message : `Failed to create ${label.toLowerCase()}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={`Add ${label}`} subheader={createTarget.kind === 'story' ? createTarget.epic.title : createTarget.kind === 'task' ? createTarget.story.title : 'Backlog'}>
      <div className={styles.editForm}>
        <label className="field-label" htmlFor="create-title">Title</label>
        <input id="create-title" autoFocus className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} />
        {createTarget.kind === 'story' && <>
          <label className="field-label" htmlFor="create-as-a">As a</label>
          <input id="create-as-a" className="text-input" value={asA} onChange={(e) => setAsA(e.target.value)} />
          <label className="field-label" htmlFor="create-i-want">I want</label>
          <input id="create-i-want" className="text-input" value={iWant} onChange={(e) => setIWant(e.target.value)} />
          <label className="field-label" htmlFor="create-so-that">So that</label>
          <input id="create-so-that" className="text-input" value={soThat} onChange={(e) => setSoThat(e.target.value)} />
        </>}
        {createTarget.kind !== 'story' && <>
          <label className="field-label" htmlFor="create-description">Description</label>
          <textarea id="create-description" className="textarea" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
        </>}
        {createTarget.kind !== 'task' && <>
          <label className="field-label" htmlFor="create-feature">Feature area</label>
          <input id="create-feature" className="text-input" value={featureArea} onChange={(e) => setFeatureArea(e.target.value)} />
        </>}
        <div className={styles.editActions}>
          <button className="btn btn-secondary btn-sm" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary btn-sm" onClick={() => void save()} disabled={saving || !title.trim()}>{saving ? 'Adding…' : `Add ${label}`}</button>
        </div>
      </div>
    </Modal>
  )
}
