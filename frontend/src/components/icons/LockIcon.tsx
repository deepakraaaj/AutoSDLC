/** Small inline lock glyph for role-gated controls — matches the codebase's
 * existing convention of inline SVG icons (e.g. Sidebar.tsx's gear icon)
 * instead of an icon font or emoji. Shared so ActionBar/Sidebar don't each
 * duplicate the markup. */
export function LockIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="4.5" y="9" width="11" height="8" rx="1.5" />
      <path d="M6.5 9V6.5a3.5 3.5 0 0 1 7 0V9" />
    </svg>
  )
}
