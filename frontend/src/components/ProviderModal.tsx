import { useEffect, useState } from 'react'
import { ApiError, getProviders, selectProvider } from '../api/client'
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

function Meter({ label, meter }: { label: string; meter: ProviderUsageMeter }) {
  const pct = meter.limit > 0 ? Math.min(100, (meter.used / meter.limit) * 100) : 0
  const tone = meterTone(meter.used, meter.limit)
  const windowLabel = meter.window === 'day' ? '/day' : '/min'
  return (
    <div className={styles.meter}>
      <div className={styles.meterLabel}>
        <span>{label}</span>
        <b>
          {meter.used.toLocaleString()} / {meter.limit.toLocaleString()}
          {windowLabel}
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
        <Meter label="Requests" meter={provider.usage.requests} />
        {provider.usage.tokens && <Meter label="Tokens" meter={provider.usage.tokens} />}
      </div>

      {provider.usage.last_error && <div className={styles.errorNote}>Last call failed: {provider.usage.last_error}</div>}

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
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState<string | null>(null)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      setData(await getProviders())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load provider status')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) void load()
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
      {loading && !data && <p className="text-muted">Loading provider status…</p>}
      {error && <div className={styles.errorNote} style={{ marginBottom: 'var(--space-4)' }}>{error}</div>}

      {data && (
        <div className={styles.list}>
          {data.providers.map((p) => (
            <ProviderCard key={p.id} provider={p} busy={switching === p.id} onSelect={() => void handleSelect(p.id)} />
          ))}
        </div>
      )}

      <div className="field-hint">
        Requests/tokens are tracked from generations run in this app, not fetched from the provider live — the
        meters reset when a window rolls over (per minute) or the next day (daily budgets). Switching providers
        takes effect on the next generation.
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-5)' }}>
        <button className="btn btn-ghost btn-sm" disabled={loading} onClick={() => void load()}>
          Refresh
        </button>
        <button className="btn btn-secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  )
}
