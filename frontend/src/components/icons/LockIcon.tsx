import { Lock } from 'lucide-react'

/** Shared lock glyph for role-gated controls. */
export function LockIcon({ className }: { className?: string }) {
  return <Lock className={className} aria-hidden="true" />
}
