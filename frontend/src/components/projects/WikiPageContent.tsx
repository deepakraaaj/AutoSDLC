import { useEffect, useState } from 'react'
import type { WikiPage } from '../../types'
import { formatDate, formatRelative } from '../../lib/format'
import styles from './WikiSection.module.css'
import { AnimatedEmptyVisual } from '../AnimatedEmptyVisual'

/** Renders one section's plain-text body: blank-line-separated paragraphs,
 * with any block made entirely of "- "-prefixed lines rendered as a list.
 * No markdown dependency — the model's output is a contract this app writes
 * (see WIKI_PROJECT_SYSTEM/WIKI_REPO_SYSTEM), not arbitrary markdown to parse. */
function WikiBody({ text }: { text: string }) {
  const visibleText = text
    .replace(/\s*Evidence:\s*(?:[\w .-]+\/)*[\w .-]+\.(?:py|java|js|jsx|ts|tsx|json|ya?ml|md|html):\d+(?:\s*,\s*(?:[\w .-]+\/)*[\w .-]+\.(?:py|java|js|jsx|ts|tsx|json|ya?ml|md|html):\d+)*\.?\s*$/i, '')
    .replace(/`?src\/[\w./ -]+:\d+`?/gi, '')
  const blocks = visibleText.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean)
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split('\n').map((l) => l.trim()).filter(Boolean)
        if (lines.length > 0 && lines.every((l) => l.startsWith('- '))) {
          return (
            <ul key={i}>
              {lines.map((l, j) => (
                <li key={j}>{l.slice(2)}</li>
              ))}
            </ul>
          )
        }
        return <p key={i}>{block}</p>
      })}
    </>
  )
}

/**
 * One wiki page's rendered content, or the "nothing generated yet" state with
 * a call to action — shared between the full Project Settings > Wiki editor
 * (WikiSection) and the read-oriented panel on a backlog's Overview tab
 * (OverviewWikiPanel), so the two don't drift into two different renderings
 * of the same page.
 */
export function WikiPageContent({
  page,
  emptyLabel,
  generating,
  progressMessage,
  onGenerate,
  regenerateLabel = 'Regenerate',
}: {
  page: WikiPage | undefined
  /** "the project" / "this repo" / a repo's name — completes "No wiki generated yet for {emptyLabel}." */
  emptyLabel: string
  generating: boolean
  /** Backend-emitted job status. Never synthesized from elapsed time. */
  progressMessage?: string
  onGenerate: () => void
  regenerateLabel?: string
}) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  useEffect(() => {
    if (!generating) {
      setElapsedSeconds(0)
      return
    }
    const startedAt = Date.now()
    const update = () => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [generating])

  const progress = generating && (
    <div className={styles.generationStatus} role="status" aria-live="polite">
      <div className={styles.generationStatusHead}>
        <span className="btn-spinner" aria-hidden="true" />
        <strong>{progressMessage || 'Background job is running…'}</strong>
        <span>{elapsedSeconds}s</span>
      </div>
      <div className={styles.generationTrack}><span /></div>
      <small>Large repositories can take a minute or more on the first scan. Unchanged revisions use the cached code index.</small>
    </div>
  )

  if (!page) {
    return (
      <div className={styles.empty}>
        <AnimatedEmptyVisual variant="overview" />
        <p>No overview generated yet for {emptyLabel}.</p>
        <button className="btn btn-primary btn-sm" disabled={generating} onClick={onGenerate}>
          {generating && <span className="btn-spinner" />}
          {generating ? 'Generating…' : 'Generate overview'}
        </button>
        {progress}
      </div>
    )
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <h2 className={styles.pageTitle}>{page.title}</h2>
        <div className={styles.facts}>
          <span title={formatDate(page.generated_at)}>Updated {formatRelative(page.generated_at)}</span>
        </div>
        <button className="btn btn-secondary btn-sm" disabled={generating} onClick={onGenerate}>
          {generating && <span className="btn-spinner" />}
          {generating ? 'Regenerating…' : regenerateLabel}
        </button>
      </div>
      {progress}
      <p className={styles.summary}>{page.summary}</p>
      {page.sections.map((section, i) => (
        <section key={i} className={styles.section}>
          <h3>{section.heading}</h3>
          <WikiBody text={section.body} />
        </section>
      ))}
    </>
  )
}
