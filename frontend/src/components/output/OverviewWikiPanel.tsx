import { useEffect, useState } from 'react'
import { ApiError, generateProjectWiki, generateRepoWiki, getProject, getProjectWiki } from '../../api/client'
import type { ProjectDetail, ProjectWiki, WikiPage, WikiClarificationQuestion } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { WikiPageContent } from '../projects/WikiPageContent'
import styles from './OverviewWikiPanel.module.css'
import { WikiClarificationForm } from '../projects/WikiClarificationForm'

/** 'project' = the project-level page; a number = that repo's page — same
 * addressing WikiSection uses in Project Settings. */
type WikiKey = 'project' | number

/**
 * The project's wiki, read from the Overview tab of any backlog under it —
 * "Product wiki" by default, with a dropdown to switch to a linked repo's
 * page when the project has any. Generation-capable here too (not just
 * read-only), via the same endpoints WikiSection uses in Project Settings,
 * so a missing page doesn't require leaving the backlog to go create one.
 */
export function OverviewWikiPanel({ projectId }: { projectId: number }) {
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [wiki, setWiki] = useState<ProjectWiki | null>(null)
  const [activeKey, setActiveKey] = useState<WikiKey>('project')
  const [generating, setGenerating] = useState<WikiKey | null>(null)
  const [generationMessage, setGenerationMessage] = useState('')
  const [clarification, setClarification] = useState<{ key: WikiKey; questions: WikiClarificationQuestion[] } | null>(null)
  const { showToast } = useToast()

  async function load() {
    try {
      const [d, w] = await Promise.all([getProject(projectId), getProjectWiki(projectId)])
      setDetail(d)
      setWiki(w)
    } catch (e) {
      showToast('Failed to load wiki', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  function pageFor(key: WikiKey): WikiPage | undefined {
    if (!wiki) return undefined
    return wiki.pages.find((p) => (key === 'project' ? p.repo_id === null : p.repo_id === key))
  }

  async function handleGenerate(key: WikiKey, answers?: Record<string, string>) {
    setGenerating(key)
    setGenerationMessage('Queued — waiting for a background worker…')
    try {
      const result = key === 'project'
        ? await generateProjectWiki(projectId, setGenerationMessage, answers)
        : await generateRepoWiki(projectId, key, setGenerationMessage, answers)
      if (result.needs_clarification) {
        setClarification({ key, questions: result.questions })
        return
      }
      setClarification(null)
      await load()
    } catch (e) {
      showToast('Failed to generate wiki', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setGenerating(null)
      setGenerationMessage('')
    }
  }

  if (detail === null || wiki === null) {
    return (
      <div className={styles.panel} aria-busy="true">
        <SkeletonList rows={1} />
      </div>
    )
  }

  const activePage = pageFor(activeKey)
  const activeLabel =
    activeKey === 'project'
      ? 'the project'
      : detail.repos.find((r) => r.id === activeKey)?.label || detail.repos.find((r) => r.id === activeKey)?.repo_slug || 'this repo'

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <h2>Overview</h2>
        {detail.repos.length > 0 && (
          <select
            className={`select ${styles.select}`}
            value={String(activeKey)}
            onChange={(e) => setActiveKey(e.target.value === 'project' ? 'project' : Number(e.target.value))}
            aria-label="Overview source"
          >
            <option value="project">Product overview</option>
            {detail.repos.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.label || repo.repo_slug}
              </option>
            ))}
          </select>
        )}
      </div>
      <WikiPageContent
        page={activePage}
        emptyLabel={activeLabel}
        generating={generating === activeKey}
        progressMessage={generating === activeKey ? generationMessage : undefined}
        onGenerate={() => void handleGenerate(activeKey)}
        regenerateLabel="Regenerate"
      />
      {clarification?.key === activeKey && <WikiClarificationForm questions={clarification.questions} submitting={generating === activeKey} onSubmit={(answers) => void handleGenerate(activeKey, answers)} />}
    </div>
  )
}
