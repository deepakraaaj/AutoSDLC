import { useEffect, useState } from 'react'
import { ApiError, getProviders, refreshProviders, selectProvider } from '../api/client'
import type { ProviderInfo, ProviderList, ProviderUsageMeter } from '../types'
import { Modal } from './Modal'
import styles from './ProviderModal.module.css'

function meterTone(used: number, limit: number): 'ok' | 'warn' | 'danger' {
  if (limit <= 0) return 'ok'
  const ratio = used / limit
  if (ratio >= 0.9) return 'danger'
  if (ratio >= 0.7) return 'warn'
  return 'ok'
}

function relativeTime(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  return `${minutes}m ago`
}

function windowLabel(w: ProviderUsageMeter['window']): string {
  if (w === 'day') return '/day'
  if (w === 'minute') return '/min'
  return ''
}

function Meter({ label, meter }: { label: string; meter: ProviderUsageMeter }) {
  const pct = meter.limit > 0 ? Math.min(100, (meter.used / meter.limit) * 100) : 0
  const tone = meterTone(meter.used, meter.limit)
  return (
    <div className={styles.meter}>
      <div className={styles.meterLabel}>
        <span>{label}</span>
        <b>
          {meter.used.toLocaleString()} / {meter.limit.toLocaleString()}
          {windowLabel(meter.window)}
        </b>
      </div>
      <div className={styles.meterTrack}>
        <div className={`${styles.meterFill} ${styles[tone]}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ProviderCard({
  provider,
  busy,
  onSelect,
}: {
  provider: ProviderInfo
  busy: boolean
  onSelect: () => void
}) {
  const { usage } = provider
  return (
    <div
      className={`${styles.card} ${provider.active ? styles.active : ''} ${!provider.configured ? styles.unconfigured : ''}`}
    >
      <div className={styles.cardHead}>
        <div className={styles.cardTitle}>
          <strong>{provider.label}</strong>
          <span>{provider.model}</span>
        </div>
        {provider.active ? (
          <span className={`${styles.badge} ${styles.badgeActive}`}>Active</span>
        ) : !provider.configured ? (
          <span className={`${styles.badge} ${styles.badgeUnconfigured}`}>No API key</span>
        ) : null}
      </div>

      <div className={styles.meters}>
        <Meter label="Requests" meter={usage.requests} />
        {usage.tokens && <Meter label="Tokens" meter={usage.tokens} />}
      </div>

      <div className={styles.liveNote}>
        {usage.live ? (
          <>
            <span className={styles.liveDot} /> {usage.no_live_numbers ? 'Confirmed reachable' : 'Live'} — checked{' '}
            {usage.checked_at ? relativeTime(usage.checked_at) : 'just now'}
            {usage.no_live_numbers && ' (this provider doesn’t expose quota numbers — meters below are estimated)'}
          </>
        ) : (
          'Estimated from generations run in this app — hit Refresh for real numbers'
        )}
      </div>

      {usage.last_error && <div className={styles.errorNote}>{usage.last_error}</div>}

      {!provider.active && provider.configured && (
        <div className={styles.cardFooter}>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={onSelect}>
            {busy && <span className="btn-spinner" />}
            Use {provider.label}
          </button>
        </div>
      )}
    </div>
  )
}

export function ProviderModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [data, setData] = useState<ProviderList | null>(null)
  const [checking, setChecking] = useState(false)
  const [switching, setSwitching] = useState<string | null>(null)
  const [error, setError] = useState('')

  async function checkLive() {
    setChecking(true)
    setError('')
    try {
      setData(await refreshProviders())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to check live provider status')
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    if (!open) return
    // Show cached status instantly, then upgrade to a live probe in the
    // background rather than blocking the modal open on 3 network calls.
    void getProviders()
      .then(setData)
      .catch(() => undefined)
    void checkLive()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function handleSelect(id: string) {
    setSwitching(id)
    setError('')
    try {
      setData(await selectProvider(id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to switch provider')
    } finally {
      setSwitching(null)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="AI Provider" subheader="Choose which provider generates your backlog, and see how much of its quota is left.">
      {!data && <p className="text-muted">Loading provider status…</p>}
      {error && <div className={styles.errorNote} style={{ marginBottom: 'var(--space-4)' }}>{error}</div>}

      {data && (
        <div className={styles.list}>
          {data.providers.map((p) => (
            <ProviderCard key={p.id} provider={p} busy={switching === p.id} onSelect={() => void handleSelect(p.id)} />
          ))}
        </div>
      )}

      <div className="field-hint">Switching providers takes effect on the next generation.</div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-5)' }}>
        <button className="btn btn-ghost btn-sm" disabled={checking} onClick={() => void checkLive()}>
          {checking && <span className="btn-spinner" />}
          {checking ? 'Checking…' : 'Refresh'}
        </button>
        <button className="btn btn-secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  )
}
