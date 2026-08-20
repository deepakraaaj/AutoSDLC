import { backlogPath, type BacklogView } from '../../lib/route'
import styles from './BacklogTabs.module.css'

const VIEWS: { id: BacklogView; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'epics', label: 'Epics' },
  { id: 'stories', label: 'Stories' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'tests', label: 'Test Cases' },
  { id: 'hierarchy', label: 'Hierarchy' },
]

/** Navigation between a generation's pages. These are real <a href> elements, not
 * buttons: that's what makes cmd/ctrl-click, middle-click and "Open in new tab" work
 * natively, which is the entire point of putting the generation id in the URL. A
 * plain left click is intercepted for client-side routing so it stays a SPA. */
export function BacklogTabs({
  genId,
  active,
  counts,
  onNavigate,
}: {
  genId: number | null
  active: BacklogView
  counts: Partial<Record<BacklogView, number>>
  onNavigate: (view: BacklogView) => void
}) {
  return (
    <nav className={styles.bar} aria-label="Backlog views">
      {VIEWS.map((v) => {
        const count = counts[v.id]
        return (
          <a
            key={v.id}
            href={backlogPath(genId, v.id)}
            aria-current={active === v.id ? 'page' : undefined}
            className={`${styles.tab} ${active === v.id ? styles.tabActive : ''}`}
            onClick={(e) => {
              // Let the browser handle anything that means "somewhere else, not here":
              // modified clicks and non-primary buttons open a new tab/window.
              if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
              e.preventDefault()
              onNavigate(v.id)
            }}
          >
            {v.label}
            {count != null && <span className={styles.count}>{count}</span>}
          </a>
        )
      })}
    </nav>
  )
}
