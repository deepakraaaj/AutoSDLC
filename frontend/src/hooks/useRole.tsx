import { createContext, useContext, useState, type ReactNode } from 'react'
import {
  canAccessProviderSettings,
  canAccessWorkflowVisualizer,
  canPushToRedmine,
  canUseOneClickGeneration,
  loadRole,
  saveRole,
  type Role,
} from '../lib/roles'

interface RoleContextValue {
  role: Role
  setRole: (role: Role) => void
  canUseOneClickGeneration: boolean
  canPushToRedmine: boolean
  canAccessProviderSettings: boolean
  canAccessWorkflowVisualizer: boolean
}

const RoleContext = createContext<RoleContextValue | null>(null)

/** Mirrors ToastProvider (useToast.tsx) — one Context mounted once in
 * main.tsx, reached directly by whichever component needs it via useRole()
 * below, instead of role/permission booleans threaded through every
 * intermediate component as props. */
export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role>(loadRole)

  function setRole(value: Role) {
    setRoleState(value)
    saveRole(value)
  }

  const value: RoleContextValue = {
    role,
    setRole,
    canUseOneClickGeneration: canUseOneClickGeneration(role),
    canPushToRedmine: canPushToRedmine(role),
    canAccessProviderSettings: canAccessProviderSettings(role),
    canAccessWorkflowVisualizer: canAccessWorkflowVisualizer(role),
  }

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>
}

export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext)
  if (!ctx) throw new Error('useRole must be used within a RoleProvider')
  return ctx
}
