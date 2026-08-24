/** UI-only role gating — no login/auth exists in this app, so this is a
 * client-side dropdown (persisted to localStorage) that hides/disables
 * generation and Redmine actions based on a self-selected role. It is not
 * real security: the backend endpoints stay unauthenticated, so this only
 * shapes what the browser offers, not what's actually reachable via the
 * API. Single source of truth for the permission matrix so gating logic
 * across components (Sidebar, GenerationSettings, ActionBar, DetailModal,
 * AssistantWindow) stays consistent. */

export type Role = 'admin' | 'manager' | 'contributor'

export const ROLES: Role[] = ['admin', 'manager', 'contributor']

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Admin',
  manager: 'Manager',
  contributor: 'Contributor',
}

export function canUseOneClickGeneration(role: Role): boolean {
  return role === 'admin'
}

export function canPushToRedmine(role: Role): boolean {
  return role === 'admin' || role === 'manager'
}

export function canPushToBitbucket(role: Role): boolean {
  return role === 'admin' || role === 'manager'
}

export function canAccessProviderSettings(role: Role): boolean {
  return role === 'admin'
}

/** The workflow visualizer (per-epic phase status + click-anything-to-edit)
 * is hidden entirely for non-admins rather than shown-and-locked — it's a
 * whole view, not a single gated action, so there's no one button to
 * disable-with-a-toast the way canPushToRedmine/canAccessProviderSettings
 * work. Mirrors how canUseOneClickGeneration hides its <option> outright. */
export function canAccessWorkflowVisualizer(role: Role): boolean {
  return role === 'admin'
}

/** Single source of truth for denial copy — every place that blocks an
 * action for a role (buttons, hints, chat replies) quotes these instead of
 * hand-typing the same sentence, so the wording only ever needs to change
 * in one place. */
export const DENIED_MESSAGES = {
  oneClickGeneration: 'Only Admins can generate everything at once.',
  pushToRedmine: 'Only Admins and Managers can push to Redmine.',
  pushToBitbucket: 'Only Admins and Managers can push to Bitbucket.',
  providerSettings: 'Only Admins can change the AI provider.',
} as const

const STORAGE_KEY = 'user-role'

/** Defaults to 'admin' — an unrecognized/missing role should leave existing
 * behavior fully unlocked rather than surprise a first-time user by hiding
 * things they had access to before this feature existed. */
export function loadRole(): Role {
  const saved = localStorage.getItem(STORAGE_KEY)
  return saved === 'admin' || saved === 'manager' || saved === 'contributor' ? saved : 'admin'
}

export function saveRole(role: Role): void {
  localStorage.setItem(STORAGE_KEY, role)
}
