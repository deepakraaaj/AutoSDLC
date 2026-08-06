import { useEffect, useState } from 'react'
import { ApiError, deleteHistoryItem, listHistory } from '../../api/client'
import type { HistoryListItem } from '../../types'
import { formatDate } from '../../lib/format'
import { useToast } from '../../hooks/useToast'
import styles from './HistoryTab.module.css'

export function HistoryTab({ onOpen }: { onOpen: (id: number) => void }) {
  const [items, setItems] = useState<HistoryListItem[] | null>(null)
  const [pendingDelete, setPendingDelete] = useState<number | null>(null)
  const { showToast } = useToast()

  async function load() {
    try {
      const data = await listHistory()
      setItems(data.generations || [])
    } catch {
      setItems([])
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function handleDelete(e: React.MouseEvent, id: number) {
    e.stopPropagation()
    if (pendingDelete !== id) {
      setPendingDelete(id)
      return
    }
    try {
      await deleteHistoryItem(id)
      setItems((prev) => (prev || []).filter((g) => g.id !== id))
      showToast('Deleted', 'Generation removed from history.', 'info')
    } catch (e) {
      showToast('Delete failed', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setPendingDelete(null)
    }
  }

  return (
    <div className="card">
      {items === null ? (
        <p className="text-muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-muted">No past generations yet</p>
      ) : (
        <div className={styles.list}>
          {items.map((gen) => {
            const quality = gen.metrics
              ? Math.round((gen.metrics.story_metrics.overall + gen.metrics.task_metrics.overall) / 2)
              : null
            return (
              <div key={gen.id} className={styles.item} onClick={() => onOpen(gen.id)}>
                <div className={styles.meta}>
                  <div className={styles.date}>{formatDate(gen.created_at)}</div>
                  <div className={styles.name}>{gen.project_name}</div>
                  <div className={styles.score}>{quality != null ? `${quality}% quality` : '—'}</div>
                </div>
                <button
                  className={`btn btn-sm ${pendingDelete === gen.id ? 'btn-danger' : 'btn-ghost'} ${styles.deleteBtn}`}
                  onClick={(e) => void handleDelete(e, gen.id)}
                  onBlur={() => setPendingDelete(null)}
                >
                  {pendingDelete === gen.id ? 'Confirm?' : 'Delete'}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
