import { useEffect, useRef, useState, type CSSProperties } from 'react'
import {
  ChevronRight,
  FileText,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import { getHealth, listProjects } from '../api/client'
import type { ProjectListItem } from '../types'
import { ThemeToggle } from './ThemeToggle'
import { ProviderModal } from './ProviderModal'
import { IntegrationsModal } from './IntegrationsModal'
import { DENIED_MESSAGES, ROLES, ROLE_LABELS, type Role } from '../lib/roles'
import { useRole } from '../hooks/useRole'
import { useRoleGatedAction } from '../hooks/useRoleGatedAction'
import { LockIcon } from './icons/LockIcon'
import { APP_ICONS } from './icons/appIcons'
import styles from './Sidebar.module.css'

/** Four destinations, not seven. Brief/Chat/Upload were three doors to one action
 * and collapsed into Create (see CreateTab); Backlog and History were two views of
 * one object and collapsed into Backlogs (the list, and any one backlog under it). */
export type TabId = 'projects' | 'create' | 'backlogs' | 'assistant'
export type ProjectArea = 'overview' | 'planning' | 'backlog' | 'pull-requests'

const NAV: { id: TabId; label: string; icon: LucideIcon }[] = [
  { id: 'projects', label: 'Overview', icon: APP_ICONS.overview },
  { id: 'create', label: 'Generate', icon: Sparkles },
  { id: 'backlogs', label: 'Backlog', icon: APP_ICONS.backlog },
  { id: 'assistant', label: 'Assistant', icon: APP_ICONS.assistant },
]

export function Sidebar({
  active,
  activeProjectId,
  onChange,
  onOpenProject,
  onOpenProjectArea,
}: {
  active: TabId
  activeProjectId?: number | null
  onChange: (id: TabId) => void
  onOpenProject?: (projectId: number) => void
  onOpenProjectArea?: (projectId: number, area: ProjectArea) => void
}) {
  const [provider, setProvider] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [projects, setProjects] = useState<ProjectListItem[]>([])
  const [projectsExpanded, setProjectsExpanded] = useState<boolean>(true)
  const [expandedProjectId, setExpandedProjectId] = useState<number | null>(activeProjectId ?? null)
  const [providerModalOpen, setProviderModalOpen] = useState(false)
  const [integrationsModalOpen, setIntegrationsModalOpen] = useState(false)
  const [workspaceOpen, setWorkspaceOpen] = useState(false)
  const workspaceRef = useRef<HTMLDivElement>(null)
  const { role, setRole, canAccessProviderSettings } = useRole()
  const gatedProviderClick = useRoleGatedAction(canAccessProviderSettings, DENIED_MESSAGES.providerSettings)

  function refreshHealth() {
    getHealth()
      .then((d) => {
        setProvider(d.provider)
        setOffline(false)
      })
      .catch(() => setOffline(true))
  }

  function refreshProjects() {
    listProjects()
      .then((d) => setProjects(d.projects))
      .catch(() => setProjects([]))
  }

  useEffect(() => {
    refreshHealth()
  }, [])

  useEffect(() => {
    refreshProjects()
  }, [active, activeProjectId])

  useEffect(() => {
    if (activeProjectId != null) setExpandedProjectId(activeProjectId)
  }, [activeProjectId])

  useEffect(() => {
    if (!workspaceOpen) return
    function onPointerDown(e: MouseEvent) {
      if (!workspaceRef.current?.contains(e.target as Node)) setWorkspaceOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setWorkspaceOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [workspaceOpen])

  return (
    <nav className={styles.sidebar} aria-label="Primary">
      <div className={styles.brand}>
        <span className={styles.mark} aria-hidden="true">
          <FileText />
        </span>
        <div>
          <div className={styles.title}>AutoSDLC</div>
          <div className={styles.tagline}>Product delivery intelligence</div>
        </div>
      </div>

      <div className={styles.navSectionLabel}>Workspace</div>

      {/* --nav-count drives the phone bottom bar's grid columns — see
          Sidebar.module.css. Derived from NAV so adding a destination can
          never silently clip the last one off the bar again. */}
      <div className={styles.nav} style={{ '--nav-count': NAV.length } as CSSProperties}>
        {NAV.map((item) => {
          const Icon = item.icon
          if (item.id === 'projects') {
            return (
              <div key="projects" className={styles.projectNavGroup}>
                <div className={styles.projectNavRow}>
                  <button
                    aria-current={active === 'projects' && activeProjectId == null ? 'page' : undefined}
                    className={`${styles.navItem} ${styles.navItemProjects} ${active === 'projects' ? styles.active : ''}`}
                    onClick={() => onChange('projects')}
                  >
                    <span className={styles.navIcon}><Icon aria-hidden="true" /></span>
                    <span className={styles.navLabel}>{item.label}</span>
                  </button>
                  <button
                    type="button"
                    className={`${styles.expandBtn} ${projectsExpanded ? styles.expandBtnExpanded : ''}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      setProjectsExpanded((v) => !v)
                    }}
                    aria-label={projectsExpanded ? 'Collapse projects' : 'Expand projects'}
                    title={projectsExpanded ? 'Collapse projects' : 'Expand projects'}
                  >
                    <ChevronRight aria-hidden="true" />
                  </button>
                </div>

                {projectsExpanded && (
                  <div className={styles.projectSubList}>
                    <button
                      type="button"
                      className={`${styles.projectSubItem} ${active === 'projects' && activeProjectId == null ? styles.projectSubItemActive : ''}`}
                      onClick={() => onChange('projects')}
                    >
                      <span className={styles.projectSubName}>All projects</span>
                    </button>
                    {projects.map((p) => {
                      const expanded = expandedProjectId === p.id
                      const selected = active === 'projects' && activeProjectId === p.id
                      return (
                        <div key={p.id} className={styles.projectTreeItem}>
                          <div className={styles.projectTreeRow}>
                            <button
                              type="button"
                              className={`${styles.projectSubItem} ${selected ? styles.projectSubItemActive : ''}`}
                              onClick={() => {
                                setExpandedProjectId(p.id)
                                if (onOpenProject) onOpenProject(p.id)
                                else onChange('projects')
                              }}
                              title={p.name}
                            >
                              <span className={styles.projectSubName}>{p.name}</span>
                              {p.ticket_prefix && <span className={styles.projectSubPrefix}>{p.ticket_prefix}</span>}
                            </button>
                            <button
                              type="button"
                              className={`${styles.projectTreeToggle} ${expanded ? styles.projectTreeToggleOpen : ''}`}
                              onClick={() => setExpandedProjectId(expanded ? null : p.id)}
                              aria-label={expanded ? `Collapse ${p.name}` : `Expand ${p.name}`}
                            >
                              <ChevronRight aria-hidden="true" />
                            </button>
                          </div>
                          {expanded && (
                            <div className={styles.projectAreas}>
                              {([
                                ['overview', 'Overview', APP_ICONS.overview],
                                ['planning', 'Planning', APP_ICONS.planning],
                                ['backlog', 'Backlog', APP_ICONS.backlog],
                                ['pull-requests', 'Pull Requests', APP_ICONS.pullRequests],
                              ] as const).map(([area, label, AreaIcon]) => (
                                <button key={area} type="button" onClick={() => onOpenProjectArea?.(p.id, area)}>
                                  <AreaIcon aria-hidden="true" />
                                  {label}
                                </button>
                              ))}
                              {([
                                ['Delivery', APP_ICONS.delivery],
                                ['Security / VAPT', APP_ICONS.security],
                                ['Handbook', APP_ICONS.handbook],
                              ] as const).map(([label, AreaIcon]) => (
                                <span key={label} className={styles.projectAreaSoon} title={`${label} is coming next`}>
                                  <AreaIcon aria-hidden="true" />
                                  <span>{label}</span>
                                  <small>Soon</small>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          }

          return (
            <button
              key={item.id}
              aria-current={active === item.id ? 'page' : undefined}
              className={`${styles.navItem} ${item.id === 'create' ? styles.navItemCreate : ''} ${active === item.id ? styles.active : ''}`}
              onClick={() => onChange(item.id)}
            >
              <span className={styles.navIcon}><Icon aria-hidden="true" /></span>
              <span className={styles.navLabel}>{item.label}</span>
            </button>
          )
        })}
      </div>

      {/* One status line and one button, rather than the five controls that used to
          sit here — a role <select>, the provider text, a gear, an integrations
          icon and a theme toggle, side by side in a 248px column. Everything except
          the connection status now lives in the Workspace popover below, which is
          also a better home for the role picker: it is a demo affordance
          (see lib/roles.ts — "not real security"), not a signed-in identity. */}
      <div className={styles.footer} ref={workspaceRef}>
        <div className={styles.footerStatusRow}>
          <span className={`${styles.statusDot} ${offline ? styles.statusOffline : styles.statusOnline}`} />
          <button
            type="button"
            className={`${styles.statusText} ${!offline && !canAccessProviderSettings ? styles.locked : ''}`}
            onClick={gatedProviderClick(() => setProviderModalOpen(true))}
            disabled={offline}
            title={offline ? undefined : canAccessProviderSettings ? 'Change AI provider' : DENIED_MESSAGES.providerSettings}
          >
            {!offline && !canAccessProviderSettings && <LockIcon className={styles.inlineLock} />}
            {offline ? 'Backend offline' : provider ? provider : 'Connecting…'}
          </button>
          <button
            type="button"
            className={`${styles.settingsButton} ${workspaceOpen ? styles.settingsButtonOpen : ''}`}
            onClick={() => setWorkspaceOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={workspaceOpen}
            aria-label="Workspace settings"
            title="Workspace settings"
          >
            <APP_ICONS.settings aria-hidden="true" />
          </button>
        </div>

        {workspaceOpen && (
          <div className={styles.workspaceMenu} role="menu">
            <div className={styles.workspaceGroup}>
              <span className={styles.workspaceLabel}>Appearance</span>
              <div className={styles.workspaceRow}>
                <span>Theme</span>
                <ThemeToggle />
              </div>
            </div>

            <div className={styles.workspaceSeparator} />

            <button
              role="menuitem"
              className={`${styles.workspaceItem} ${!offline && !canAccessProviderSettings ? styles.locked : ''}`}
              onClick={() => {
                setWorkspaceOpen(false)
                gatedProviderClick(() => setProviderModalOpen(true))()
              }}
              title={canAccessProviderSettings ? 'Change AI provider' : DENIED_MESSAGES.providerSettings}
            >
              {!offline && !canAccessProviderSettings && <LockIcon className={styles.inlineLock} />}
              <APP_ICONS.assistant aria-hidden="true" />
              AI provider
            </button>
            <button
              role="menuitem"
              className={styles.workspaceItem}
              onClick={() => {
                setWorkspaceOpen(false)
                setIntegrationsModalOpen(true)
              }}
            >
              <APP_ICONS.integrations aria-hidden="true" />
              Integrations
            </button>

            <div className={styles.workspaceSeparator} />

            <div className={styles.workspaceGroup}>
              <span className={styles.workspaceLabel}>Role (demo only)</span>
              <select
                className={`select ${styles.roleSelect}`}
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                aria-label="Current role"
                title="Role — gates which generation and Redmine actions are available (UI-only, not real auth)"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </div>

      <IntegrationsModal open={integrationsModalOpen} onClose={() => setIntegrationsModalOpen(false)} />

      <ProviderModal
        open={providerModalOpen}
        onClose={() => {
          setProviderModalOpen(false)
          refreshHealth()
        }}
      />
    </nav>
  )
}
