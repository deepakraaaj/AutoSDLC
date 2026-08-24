import type { TabId } from '../components/Sidebar'

/** The backlog's sub-pages. Each is its own URL, so a generation's epics, its
 * hierarchy and its quality report can sit in separate browser tabs instead of
 * stacking into one very long page. */
export const BACKLOG_VIEWS = ['overview', 'epics', 'stories', 'tasks', 'tests', 'hierarchy'] as const
export type BacklogView = (typeof BACKLOG_VIEWS)[number]

/** How a brief gets into the app. These used to be three separate top-level
 * destinations (Brief / Chat / Upload) sitting alongside Projects, Backlog and
 * History, which made three doors to one action look like three features. They
 * are now one destination with a mode switch — same three components behind it,
 * see CreateTab. */
export const CREATE_MODES = ['write', 'chat', 'upload'] as const
export type CreateMode = (typeof CREATE_MODES)[number]

const APP_ROUTE_PREFIX = '/app/'
const TAB_IDS = ['projects', 'create', 'backlogs', 'assistant'] as const

export interface AppRoute {
  tab: TabId
  /** Which generation the backlog pages are showing. null means "whichever one this
   * session was last on" — the pre-id behaviour, kept so /app/backlogs still works.
   * A real id here is what makes a backlog openable in a fresh tab at all: the active
   * generation was only ever in sessionStorage, which is per-tab, so a second tab
   * opened on /app/backlogs restored nothing. */
  genId: number | null
  view: BacklogView
  /** Which input mode the Create screen is on. */
  createMode: CreateMode
  /** Which project is open, if any. */
  projectId: number | null
  /** Which project workspace section is active. */
  projectSection?: 'backlog' | 'planning' | 'settings' | 'pull-requests' | 'security' | null
}

function isTabId(value: string): value is TabId {
  return (TAB_IDS as readonly string[]).includes(value)
}

function isBacklogView(value: string): value is BacklogView {
  return (BACKLOG_VIEWS as readonly string[]).includes(value)
}

function isCreateMode(value: string): value is CreateMode {
  return (CREATE_MODES as readonly string[]).includes(value)
}

/** Paths that existed before the 7-destination nav was consolidated to 4. Anyone
 * who bookmarked, shared, or opened a second tab on one of these still lands in the
 * right place — the ids in /app/backlog/:id/:view especially, since those were
 * deliberately made shareable. Applied inside parseRoute, so every caller gets it. */
export function legacyRedirect(pathname: string): string | null {
  if (!pathname.startsWith(APP_ROUTE_PREFIX)) return null
  const segments = pathname.slice(APP_ROUTE_PREFIX.length).split('/').filter(Boolean)
  const [first, ...rest] = segments
  switch (first) {
    case 'brief':
      return createPath('write')
    case 'chat':
      return createPath('chat')
    case 'upload':
      return createPath('upload')
    case 'history':
      return tabPath('backlogs')
    // Singular -> plural, preserving /:genId and /:view exactly as given.
    case 'backlog':
      return [`${APP_ROUTE_PREFIX}backlogs`, ...rest].join('/')
    default:
      return null
  }
}

export function parseRoute(pathname: string): AppRoute {
  const redirected = legacyRedirect(pathname)
  const path = redirected ?? pathname
  const segments = path.startsWith(APP_ROUTE_PREFIX)
    ? path.slice(APP_ROUTE_PREFIX.length).split('/').filter(Boolean)
    : []
  const [first, second, third] = segments
  const tab: TabId = first && isTabId(first) ? first : 'create'
  const base: AppRoute = { tab, genId: null, view: 'overview', createMode: 'write', projectId: null, projectSection: null }

  if (tab === 'create') {
    return { ...base, createMode: second && isCreateMode(second) ? second : 'write' }
  }

  if (tab === 'projects') {
    const projectId = second && /^\d+$/.test(second) ? Number(second) : null
    let projectSection: 'backlog' | 'planning' | 'settings' | 'pull-requests' | 'security' | null = projectId != null ? 'backlog' : null
    let view: BacklogView = 'overview'

    if (third === 'settings') {
      projectSection = 'settings'
    } else if (third === 'planning') {
      projectSection = 'planning'
    } else if (third === 'pull-requests') {
      projectSection = 'pull-requests'
    } else if (third === 'security') {
      projectSection = 'security'
    } else if (third && isBacklogView(third)) {
      view = third
    }
    return { ...base, projectId, projectSection, view }
  }

  if (tab !== 'backlogs') return base

  // /app/backlogs/:genId/:view, but also /app/backlogs/:view — addressing a view of
  // the session's current generation without having to know its id.
  const genId = second && /^\d+$/.test(second) ? Number(second) : null
  const viewSegment = genId == null ? second : third
  const view: BacklogView = viewSegment && isBacklogView(viewSegment) ? viewSegment : 'overview'
  return { ...base, genId, view }
}

export function tabPath(tab: TabId): string {
  return `${APP_ROUTE_PREFIX}${tab}`
}

export function createPath(mode: CreateMode = 'write'): string {
  return mode === 'write' ? `${APP_ROUTE_PREFIX}create` : `${APP_ROUTE_PREFIX}create/${mode}`
}

export function projectPath(
  projectId: number | null,
  section?: 'backlog' | 'planning' | 'settings' | 'pull-requests' | 'security' | null,
  view?: BacklogView,
): string {
  const base = `${APP_ROUTE_PREFIX}projects`
  if (projectId == null) return base
  if (section === 'settings') return `${base}/${projectId}/settings`
  if (section === 'planning') return `${base}/${projectId}/planning`
  if (section === 'pull-requests') return `${base}/${projectId}/pull-requests`
  if (section === 'security') return `${base}/${projectId}/security`
  if (view && view !== 'overview') return `${base}/${projectId}/${view}`
  return `${base}/${projectId}`
}

export function backlogPath(genId: number | null, view: BacklogView = 'overview'): string {
  const base = `${APP_ROUTE_PREFIX}backlogs`
  const idPart = genId == null ? '' : `/${genId}`
  const viewPart = view === 'overview' ? '' : `/${view}`
  return `${base}${idPart}${viewPart}`
}

export function routePath(route: AppRoute): string {
  switch (route.tab) {
    case 'backlogs':
      return backlogPath(route.genId, route.view)
    case 'create':
      return createPath(route.createMode)
    case 'projects':
      return projectPath(route.projectId, route.projectSection, route.view)
    default:
      return tabPath(route.tab)
  }
}
