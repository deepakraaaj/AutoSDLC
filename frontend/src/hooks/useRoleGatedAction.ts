import { useToast } from './useToast'

/** Wraps a click handler for a role-gated action: fires normally when
 * `allowed`, otherwise shows an explanatory toast instead of doing nothing.
 * A plain `disabled` button only explains itself via a hover `title` —
 * invisible on touch/mobile, and gives zero feedback on tap. The button
 * stays clickable either way; only the *behavior* differs. */
export function useRoleGatedAction(allowed: boolean, deniedMessage: string) {
  const { showToast } = useToast()
  return (onClick: () => void) => () => {
    if (allowed) onClick()
    else showToast('Restricted', deniedMessage, 'warning')
  }
}
