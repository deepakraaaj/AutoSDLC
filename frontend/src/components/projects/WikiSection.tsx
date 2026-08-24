import { useEffect, useState } from 'react'
import { ApiError, generateProjectWiki, generateRepoWiki, getProjectWiki } from '../../api/client'
import type { ProjectDetail, ProjectWiki, WikiPage } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { WikiPageContent } from './WikiPageContent'
import styles from './WikiSection.module.css'

/** 'project' = the project-level page (repo_id null); a number = that repo's
 * page (repo_id set). Matches how the backend addresses the same two cases. */
type WikiKey = 'project' | number

export function WikiSection({ detail }: { detail: ProjectDetail }) {
  const [wiki, setWiki] = useState<ProjectWiki | null>(null)
  const [activeKey, setActiveKey] = useState<WikiKey>('project')
  const [generating, setGenerating] = useState<WikiKey | null>(null)
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

  async function handleGenerate(key: WikiKey) {
    setGenerating(key)
    try {
      if (key === 'project') await generateProjectWiki(detail.id)
      else await generateRepoWiki(detail.id, key)
      await load()
    } catch (e) {
      showToast('Failed to generate wiki', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setGenerating(null)
    }
  }

  const activePage = pageFor(activeKey)
  const activeLabel =
    activeKey === 'project'
      ? 'the project'
      : detail.repos.find((r) => r.id === activeKey)?.label || detail.repos.find((r) => r.id === activeKey)?.repo_slug || 'this repo'

  return (
    <>
      <h3>Wiki</h3>
      <p className="field-hint">
        Documentation grounded in this project's brief and linked repos — one page for the project, one
        per repo. Regenerating overwrites the existing page. Also readable from the Overview tab of any backlog
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
              onGenerate={() => void handleGenerate(activeKey)}
            />
          </div>
        </div>
      )}
    </>
  )
}
