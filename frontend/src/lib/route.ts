import type { TabId } from '../components/Sidebar'

/** The backlog's sub-pages. Each is its own URL, so a generation's epics, its
 * hierarchy and its quality report can sit in separate browser tabs instead of
 * stacking into one very long page. */
export const BACKLOG_VIEWS = ['overview', 'epics', 'stories', 'tasks', 'tests', 'hierarchy'] as const
export type BacklogView = (typeof BACKLOG_VIEWS)[number]

const APP_ROUTE_PREFIX = '/app/'
const TAB_IDS = ['brief', 'chat', 'upload', 'assistant', 'backlog', 'history'] as const

export interface AppRoute {
  tab: TabId
  /** Which generation the backlog pages are showing. null means "whichever one this
   * session was last on" — the pre-id behaviour, kept so /app/backlog still works.
   * A real id here is what makes a backlog openable in a fresh tab at all: the active
   * generation was only ever in sessionStorage, which is per-tab, so a second tab
   * opened on /app/backlog restored nothing. */
  genId: number | null
  view: BacklogView
}

function isTabId(value: string): value is TabId {
  return (TAB_IDS as readonly string[]).includes(value)
}

function isBacklogView(value: string): value is BacklogView {
  return (BACKLOG_VIEWS as readonly string[]).includes(value)
}

export function parseRoute(pathname: string): AppRoute {
  const segments = pathname.startsWith(APP_ROUTE_PREFIX)
    ? pathname.slice(APP_ROUTE_PREFIX.length).split('/').filter(Boolean)
    : []
  const [first, second, third] = segments
  const tab: TabId = first && isTabId(first) ? first : 'brief'
  if (tab !== 'backlog') return { tab, genId: null, view: 'overview' }

  // /app/backlog/:genId/:view, but also /app/backlog/:view — addressing a view of
  // the session's current generation without having to know its id.
  const genId = second && /^\d+$/.test(second) ? Number(second) : null
  const viewSegment = genId == null ? second : third
  const view: BacklogView = viewSegment && isBacklogView(viewSegment) ? viewSegment : 'overview'
  return { tab, genId, view }
}

export function tabPath(tab: TabId): string {
  return `${APP_ROUTE_PREFIX}${tab}`
}

export function backlogPath(genId: number | null, view: BacklogView = 'overview'): string {
  const base = `${APP_ROUTE_PREFIX}backlog`
  const idPart = genId == null ? '' : `/${genId}`
  const viewPart = view === 'overview' ? '' : `/${view}`
  return `${base}${idPart}${viewPart}`
}

export function routePath(route: AppRoute): string {
  return route.tab === 'backlog' ? backlogPath(route.genId, route.view) : tabPath(route.tab)
}
