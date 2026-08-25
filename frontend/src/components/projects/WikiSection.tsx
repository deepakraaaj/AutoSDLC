import { useEffect, useState } from 'react'
import { ApiError, generateProjectWiki, generateRepoWiki, getProjectWiki } from '../../api/client'
import type { ProjectDetail, ProjectWiki, WikiPage, WikiClarificationQuestion } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { WikiPageContent } from './WikiPageContent'
import styles from './WikiSection.module.css'
import { WikiClarificationForm } from './WikiClarificationForm'

/** 'project' = the project-level page (repo_id null); a number = that repo's
 * page (repo_id set). Matches how the backend addresses the same two cases. */
type WikiKey = 'project' | number

export function WikiSection({ detail }: { detail: ProjectDetail }) {
  const [wiki, setWiki] = useState<ProjectWiki | null>(null)
  const [activeKey, setActiveKey] = useState<WikiKey>('project')
  const [generating, setGenerating] = useState<WikiKey | null>(null)
  const [generationMessage, setGenerationMessage] = useState('')
  const [clarification, setClarification] = useState<{ key: WikiKey; questions: WikiClarificationQuestion[] } | null>(null)
  const { showToast } = useToast()

  async function load() {
    try {
      setWiki(await getProjectWiki(detail.id))
    } catch (e) {
      showToast('Failed to load wiki', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id])

  function pageFor(key: WikiKey): WikiPage | undefined {
    if (!wiki) return undefined
    return wiki.pages.find((p) => (key === 'project' ? p.repo_id === null : p.repo_id === key))
  }

  async function handleGenerate(key: WikiKey, answers?: Record<string, string>) {
    setGenerating(key)
    setGenerationMessage('Queued — waiting for a background worker…')
    try {
      const result = key === 'project'
        ? await generateProjectWiki(detail.id, setGenerationMessage, answers)
        : await generateRepoWiki(detail.id, key, setGenerationMessage, answers)
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

  const activePage = pageFor(activeKey)
  const activeLabel =
    activeKey === 'project'
      ? 'the project'
      : detail.repos.find((r) => r.id === activeKey)?.label || detail.repos.find((r) => r.id === activeKey)?.repo_slug || 'this repo'

  return (
    <>
      <h3>Overview</h3>
      <p className="field-hint">
        Business overview generated from all linked repos, with the project brief used when available — one page for the product, one
        per repo. Regenerating publishes a new version while retaining history. Also readable from the Overview tab of any backlog
        under this project.
      </p>

      {wiki === null ? (
        <SkeletonList rows={2} />
      ) : (
        <div className={styles.layout}>
          <nav className={styles.nav} aria-label="Wiki pages">
            <button
              className={`${styles.navItem} ${activeKey === 'project' ? styles.navItemActive : ''}`}
              onClick={() => setActiveKey('project')}
            >
              Product wiki
            </button>
            {detail.repos.map((repo) => (
              <button
                key={repo.id}
                className={`${styles.navItem} ${activeKey === repo.id ? styles.navItemActive : ''}`}
                onClick={() => setActiveKey(repo.id)}
              >
                {repo.label || repo.repo_slug}
              </button>
            ))}
          </nav>

          <div className={styles.content}>
            <WikiPageContent
              page={activePage}
              emptyLabel={activeLabel}
              generating={generating === activeKey}
              progressMessage={generating === activeKey ? generationMessage : undefined}
              onGenerate={() => void handleGenerate(activeKey)}
            />
            {clarification?.key === activeKey && <WikiClarificationForm questions={clarification.questions} submitting={generating === activeKey} onSubmit={(answers) => void handleGenerate(activeKey, answers)} />}
          </div>
        </div>
      )}
    </>
  )
}
