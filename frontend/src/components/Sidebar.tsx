import { useEffect, useRef, useState, type CSSProperties } from 'react'
import {
  ChevronRight,
  FileText,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import { getHealth, listProjects } from '../api/client'
import { BUSINESS_CONTEXT_KIND_LABELS, BUSINESS_CONTEXT_KINDS, SDLC_AREAS } from '../types'
import type { BusinessContextKind, ProjectListItem, SdlcArea } from '../types'
import { AREA_ICONS, areaColorVars } from '../lib/sdlcAreaStyle'
import { ThemeToggle } from './ThemeToggle'
import { ProviderModal } from './ProviderModal'
import { IntegrationsModal } from './IntegrationsModal'
import { DENIED_MESSAGES, ROLES, ROLE_LABELS, type Role } from '../lib/roles'
import { useRole } from '../hooks/useRole'
import { useRoleGatedAction } from '../hooks/useRoleGatedAction'
import { LockIcon } from './icons/LockIcon'
import { APP_ICONS } from './icons/appIcons'
import styles from './Sidebar.module.css'

/** Five destinations, not seven. Brief/Chat/Upload were three doors to one action
 * and collapsed into Create (see CreateTab); Backlog and History were two views of
 * one object and collapsed into Backlogs (the list, and any one backlog under it).
 * Usage is the one destination that isn't a view of generated content — spend
 * reporting spans every project, so it doesn't belong nested under one. */
export type TabId = 'projects' | 'create' | 'backlogs' | 'assistant' | 'usage'
export type ProjectArea = 'overview' | 'planning' | 'backlog' | 'pull-requests' | 'security' | 'knowledge'

// Small, fixed palette rather than a computed hue — deterministic per project id
// (id % length), reads like Bitbucket's repo avatar squares, but stays legible
// against both themes without a full HSL-generation pass.
const PROJECT_COLORS = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d']
function projectColor(id: number): string {
  return PROJECT_COLORS[id % PROJECT_COLORS.length]
}

const NAV: { id: TabId; label: string; icon: LucideIcon }[] = [
  { id: 'projects', label: 'Overview', icon: APP_ICONS.overview },
  { id: 'create', label: 'Generate', icon: Sparkles },
  { id: 'backlogs', label: 'Backlog', icon: APP_ICONS.backlog },
  { id: 'assistant', label: 'Assistant', icon: APP_ICONS.assistant },
  { id: 'usage', label: 'Usage', icon: APP_ICONS.usage },
]

export function Sidebar({
  active,
  activeProjectId,
  activeProjectArea,
  activeKnowledgeArea,
  activeBusinessContextKind,
  onChange,
  onOpenProject,
  onOpenProjectArea,
  onOpenKnowledgeArea,
  onOpenBusinessContextKind,
}: {
  active: TabId
  activeProjectId?: number | null
  /** Which project area (Overview/Planning/Backlog/Pull Requests/Security) is
   * open as its own page, if any — drives highlighting the matching row in
   * the expanded project's sub-tree. Knowledge Base has its own richer prop
   * below since it drives a nested sub-tree, not just one row. */
  activeProjectArea?: ProjectArea | null
  /** Which of the 15 SDLC areas is open as its own page, if any — drives
   * highlighting the matching sub-item and keeping the Knowledge Base
   * sub-tree expanded when the route already points at one. */
  activeKnowledgeArea?: SdlcArea | null
  /** Which of Business Context's 4 structured kinds is open as its own
   * page, one level deeper — same role activeKnowledgeArea plays, for the
   * Business Context sub-tree specifically. */
  activeBusinessContextKind?: BusinessContextKind | null
  onChange: (id: TabId) => void
  onOpenProject?: (projectId: number) => void
  onOpenProjectArea?: (projectId: number, area: ProjectArea) => void
  onOpenKnowledgeArea?: (projectId: number, area: SdlcArea) => void
  onOpenBusinessContextKind?: (projectId: number, kind: BusinessContextKind) => void
}) {
  const [provider, setProvider] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [projects, setProjects] = useState<ProjectListItem[]>([])
  const [projectsExpanded, setProjectsExpanded] = useState<boolean>(true)
  const [expandedProjectId, setExpandedProjectId] = useState<number | null>(activeProjectId ?? null)
  // Starts expanded whenever the route already points at one of the 15
  // areas, so landing on a deep link doesn't hide the very item that's
  // active — same reasoning as expandedProjectId defaulting to activeProjectId.
  const [knowledgeExpanded, setKnowledgeExpanded] = useState<boolean>(Boolean(activeKnowledgeArea))
  // Same reasoning one level deeper — starts expanded when the route already
  // points at one of Business Context's 4 kinds.
  const [businessContextExpanded, setBusinessContextExpanded] = useState<boolean>(Boolean(activeBusinessContextKind))
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
    if (activeKnowledgeArea) setKnowledgeExpanded(true)
  }, [activeKnowledgeArea])

  useEffect(() => {
    if (activeBusinessContextKind) setBusinessContextExpanded(true)
  }, [activeBusinessContextKind])

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
      <div className={styles.navScroll}>
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
                              <span className={styles.projectAvatar} style={{ background: projectColor(p.id) }} aria-hidden="true">
                                {(p.name || '?').charAt(0).toUpperCase()}
                              </span>
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
                                ['security', 'Security / VAPT', APP_ICONS.security],
                              ] as const).map(([area, label, AreaIcon]) => (
                                <button
                                  key={area}
                                  type="button"
                                  className={expanded && activeProjectArea === area ? styles.projectAreaActive : ''}
                                  onClick={() => onOpenProjectArea?.(p.id, area)}
                                >
                                  <AreaIcon aria-hidden="true" />
                                  {label}
                                </button>
                              ))}

                              {/* Knowledge Base / Docs — expandable to the 15 SDLC
                                  areas (app/services/knowledge_base.py's SDLC_AREAS),
                                  each its own dedicated page. The row itself still
                                  opens the all-areas overview; the chevron is a
                                  separate hit target for the sub-list, same
                                  split-button pattern as the project row above it. */}
                              <div className={styles.knowledgeNavGroup}>
                                <div className={styles.knowledgeNavRow}>
                                  <button
                                    type="button"
                                    className={expanded && activeProjectArea === 'knowledge' && !activeKnowledgeArea ? styles.projectAreaActive : ''}
                                    onClick={() => onOpenProjectArea?.(p.id, 'knowledge')}
                                  >
                                    <APP_ICONS.knowledgeBase aria-hidden="true" />
                                    <span className={styles.knowledgeAreaLabel}>Knowledge Base / Docs</span>
                                  </button>
                                  <button
                                    type="button"
                                    className={`${styles.projectTreeToggle} ${knowledgeExpanded ? styles.projectTreeToggleOpen : ''}`}
                                    onClick={() => setKnowledgeExpanded((v) => !v)}
                                    aria-label={knowledgeExpanded ? 'Collapse SDLC areas' : 'Expand SDLC areas'}
                                  >
                                    <ChevronRight aria-hidden="true" />
                                  </button>
                                </div>
                                {knowledgeExpanded && (
                                  <div className={styles.knowledgeAreaList}>
                                    {SDLC_AREAS.map((sdlcArea) => {
                                      const AreaIcon = AREA_ICONS[sdlcArea]
                                      const isActive = active === 'projects' && activeProjectId === p.id && activeKnowledgeArea === sdlcArea && !activeBusinessContextKind
                                      // Business Context alone expands one level further, into its
                                      // own 4 structured kinds (objective/stakeholder/scope_boundary/
                                      // success_metric) — same split-row shape as the Knowledge Base
                                      // row itself one level up, just nested one deeper.
                                      if (sdlcArea === 'Business Context') {
                                        return (
                                          <div key={sdlcArea} className={styles.knowledgeNavGroup}>
                                            <div className={styles.knowledgeNavRow}>
                                              <button
                                                type="button"
                                                className={isActive ? styles.projectAreaActive : ''}
                                                onClick={() => onOpenKnowledgeArea?.(p.id, sdlcArea)}
                                                title={sdlcArea}
                                              >
                                                <span className={styles.knowledgeAreaIcon} style={areaColorVars(sdlcArea)}>
                                                  <AreaIcon aria-hidden="true" />
                                                </span>
                                                <span className={styles.knowledgeAreaLabel}>{sdlcArea}</span>
                                              </button>
                                              <button
                                                type="button"
                                                className={`${styles.projectTreeToggle} ${businessContextExpanded ? styles.projectTreeToggleOpen : ''}`}
                                                onClick={() => setBusinessContextExpanded((v) => !v)}
                                                aria-label={businessContextExpanded ? 'Collapse Business Context kinds' : 'Expand Business Context kinds'}
                                              >
                                                <ChevronRight aria-hidden="true" />
                                              </button>
                                            </div>
                                            {businessContextExpanded && (
                                              <div className={styles.businessContextKindList}>
                                                {BUSINESS_CONTEXT_KINDS.map((kind) => {
                                                  const kindActive = active === 'projects' && activeProjectId === p.id && activeBusinessContextKind === kind
                                                  return (
                                                    <button
                                                      key={kind}
                                                      type="button"
                                                      className={kindActive ? styles.projectAreaActive : ''}
                                                      onClick={() => onOpenBusinessContextKind?.(p.id, kind)}
                                                      title={BUSINESS_CONTEXT_KIND_LABELS[kind]}
                                                    >
                                                      {BUSINESS_CONTEXT_KIND_LABELS[kind]}
                                                    </button>
                                                  )
                                                })}
                                              </div>
                                            )}
                                          </div>
                                        )
                                      }
                                      return (
                                        <button
                                          key={sdlcArea}
                                          type="button"
                                          className={isActive ? styles.projectAreaActive : ''}
                                          onClick={() => onOpenKnowledgeArea?.(p.id, sdlcArea)}
                                          title={sdlcArea}
                                        >
                                          <span className={styles.knowledgeAreaIcon} style={areaColorVars(sdlcArea)}>
                                            <AreaIcon aria-hidden="true" />
                                          </span>
                                          <span className={styles.knowledgeAreaLabel}>{sdlcArea}</span>
                                        </button>
                                      )
                                    })}
                                  </div>
                                )}
                              </div>

                              {([
                                ['Delivery', APP_ICONS.delivery],
                                ['Handbook', APP_ICONS.handbook],
                              ] as const).map(([label, AreaIcon]) => (
                                <span key={label} className={styles.projectAreaSoon} title={`${label} is coming next`}>
                                  <AreaIcon aria-hidden="true" />
                                  <span>{label}</span>
                                  <span className="badge badge-violet">Soon</span>
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
      </div>

      {/* One status line and one button, rather than the five controls that used to
          sit here — a role <select>, the provider text, a gear, an integrations
          icon and a theme toggle, side by side in a 248px column. Everything except
          the connection status now lives in the Workspace popover below, which is
          also a better home for the role picker: it is a demo affordance
          (see lib/roles.ts — "not real security"), not a signed-in identity.
          Outside .navScroll so it stays pinned to the bottom of the rail
          instead of scrolling away with a long project tree. */}
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
