/**
 * Placeholder for content that is loading. Shaped like what is coming, so the
 * layout does not jump when it arrives — the `Loading…` line these replace gave
 * no hint of that.
 *
 * `aria-hidden` throughout: the surrounding region carries `aria-busy`, which is
 * what a screen reader should hear. A pile of empty boxes is noise.
 */
export function Skeleton({ width, height = 12 }: { width?: number | string; height?: number | string }) {
  return <div className="skeleton" style={{ width: width ?? '100%', height }} aria-hidden="true" />
}

/** A stack of skeleton rows standing in for a list of cards. */
export function SkeletonList({ rows = 3 }: { rows?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }} aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-2)',
            padding: 'var(--space-4)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
          }}
        >
          <Skeleton width={96} height={10} />
          <Skeleton width="45%" height={15} />
          <Skeleton width="30%" height={10} />
        </div>
      ))}
    </div>
  )
}
