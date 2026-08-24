import { useEffect, useState } from 'react'
import { ApiError, deleteHistoryItem, listHistory } from '../../api/client'
import type { HistoryListItem } from '../../types'
import { formatDate, formatDuration, formatRelative, scoreTone } from '../../lib/format'
import { useToast } from '../../hooks/useToast'
import { backlogPath } from '../../lib/route'
import { SkeletonList } from '../Skeleton'
import styles from './BacklogsTab.module.css'

export function BacklogsTab({ onOpen }: { onOpen: (id: number) => void }) {
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
    // The action lives inside a linked history row. Stopping propagation keeps the
    // React click handler from opening it, while preventDefault also stops the
    // browser from following the row's backlog URL.
    e.preventDefault()
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
        <SkeletonList />
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
                <div className={styles.cardTop}>
                  {quality != null ? (
                    <span className={`badge badge-${scoreTone(quality)}`}>{quality}% quality</span>
                  ) : (
                    <span className="badge badge-neutral">No score</span>
                  )}
                  <span className={styles.date} title={formatDate(gen.created_at)}>
                    {formatRelative(gen.created_at)}
                  </span>
                </div>
                <div className={styles.name}>{gen.project_name}</div>
                <div className={styles.score}>
                  {gen.metrics?.generation_seconds != null && formatDuration(gen.metrics.generation_seconds)}
                  {gen.metrics?.token_usage && ` · ${gen.metrics.token_usage.total_tokens.toLocaleString()} tokens`}
                </div>
                <button
                  type="button"
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
