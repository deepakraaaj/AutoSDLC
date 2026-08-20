import { useEffect, useState } from 'react'
import { ApiError, deleteHistoryItem, listHistory } from '../../api/client'
import type { HistoryListItem } from '../../types'
import { formatDate, formatDuration } from '../../lib/format'
import { useToast } from '../../hooks/useToast'
import { backlogPath } from '../../lib/route'
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
              <a
                key={gen.id}
                className={styles.item}
                href={backlogPath(gen.id)}
                onClick={(e) => {
                  // Modified/non-primary clicks stay the browser's job — that's how
                  // "open this backlog in a new tab" works without any custom handling.
                  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
                  e.preventDefault()
                  onOpen(gen.id)
                }}
              >
                <div className={styles.meta}>
                  <div className={styles.date}>{formatDate(gen.created_at)}</div>
                  <div className={styles.name}>{gen.project_name}</div>
                  <div className={styles.score}>
                    {quality != null ? `${quality}% quality` : '—'}
                    {gen.metrics?.generation_seconds != null && ` · ${formatDuration(gen.metrics.generation_seconds)}`}
                    {gen.metrics?.token_usage && ` · ${gen.metrics.token_usage.total_tokens.toLocaleString()} tokens`}
                  </div>
                </div>
                <button
                  className={`btn btn-sm ${pendingDelete === gen.id ? 'btn-danger' : 'btn-ghost'} ${styles.deleteBtn}`}
                  onClick={(e) => void handleDelete(e, gen.id)}
                  onBlur={() => setPendingDelete(null)}
                >
                  {pendingDelete === gen.id ? 'Confirm?' : 'Delete'}
                </button>
              </a>
            )
          })}
        </div>
      )}
    </div>
  )
}
