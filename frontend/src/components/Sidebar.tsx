import { useEffect, useState, type ReactNode } from 'react'
import { getHealth } from '../api/client'
import { ThemeToggle } from './ThemeToggle'
import { ProviderModal } from './ProviderModal'
import styles from './Sidebar.module.css'

export type TabId = 'brief' | 'chat' | 'upload' | 'assistant' | 'backlog' | 'history'

const NAV: { id: TabId; label: string; icon: ReactNode }[] = [
  {
    id: 'brief',
    label: 'Brief',
    icon: (
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path d="M5 2.5h7l3.5 3.5v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1Z" strokeLinejoin="round" />
        <path d="M12 2.5V6a1 1 0 0 0 1 1h3.5" strokeLinejoin="round" />
        <path d="M6.5 11h7M6.5 13.5h7M6.5 16h4.5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'chat',
    label: 'Chat',
    icon: (
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path
          d="M2.5 10a6.5 6.5 0 1 1 3.02 5.49L2.5 16.5l1.06-2.9A6.47 6.47 0 0 1 2.5 10Z"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    id: 'upload',
    label: 'Upload',
    icon: (
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path d="M10 12.5V4M6.5 7.5 10 4l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3.5 13v2.5a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V13" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: 'assistant',
    label: 'Assistant',
    icon: (
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path d="M10 2.5c-1 0-1.8.8-1.8 1.8 0 .5.2 1 .55 1.3L8 6.5H5.5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H12l-.75-.9c.35-.33.55-.8.55-1.3 0-1-.8-1.8-1.8-1.8Z" strokeLinejoin="round" />
        <circle cx="7.8" cy="11" r=".9" fill="currentColor" stroke="none" />
        <circle cx="12.2" cy="11" r=".9" fill="currentColor" stroke="none" />
        <path d="M8 14h4" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'backlog',
    label: 'Backlog',
    icon: (
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
        <rect x="2.5" y="3.5" width="15" height="3.5" rx="1" />
        <rect x="2.5" y="8.5" width="15" height="3.5" rx="1" />
        <rect x="2.5" y="13.5" width="9" height="3.5" rx="1" />
      </svg>
    ),
  },
  {
    id: 'history',
    label: 'History',
    icon: (
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
        <circle cx="10" cy="10.5" r="7" />
        <path d="M10 6.5v4l2.8 1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
]

export function Sidebar({ active, onChange }: { active: TabId; onChange: (id: TabId) => void }) {
  const [provider, setProvider] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [providerModalOpen, setProviderModalOpen] = useState(false)

  function refreshHealth() {
    getHealth()
      .then((d) => {
        setProvider(d.provider)
        setOffline(false)
      })
      .catch(() => setOffline(true))
  }

  useEffect(() => {
    refreshHealth()
  }, [])

  return (
    <nav className={styles.sidebar} aria-label="Primary">
      <div className={styles.brand}>
        <span className={styles.mark} aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
        </span>
        <div>
          <div className={styles.title}>AutoSDLC</div>
          <div className={styles.tagline}>Brief in, backlog out.</div>
        </div>
      </div>

      <div className={styles.nav} role="tablist" aria-label="Input mode">
        {NAV.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={active === item.id}
            className={`${styles.navItem} ${active === item.id ? styles.active : ''}`}
            onClick={() => onChange(item.id)}
          >
            <span className={styles.navIcon}>{item.icon}</span>
            {item.label}
          </button>
        ))}
      </div>

      <div className={styles.footer}>
        <span className={`${styles.statusDot} ${offline ? styles.statusOffline : styles.statusOnline}`} />
        <button
          type="button"
          className={styles.statusText}
          onClick={() => setProviderModalOpen(true)}
          disabled={offline}
          title="Change AI provider"
        >
          {offline ? 'Backend offline' : provider ? `Provider: ${provider}` : 'Connecting…'}
        </button>
        <button
          type="button"
          className={styles.settingsButton}
          onClick={() => setProviderModalOpen(true)}
          disabled={offline}
          aria-label="AI provider settings"
          title="AI provider settings"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="10" cy="10" r="2.6" />
            <path
              d="M10 2.8v1.9M10 15.3v1.9M17.2 10h-1.9M4.7 10H2.8M15.1 4.9l-1.35 1.35M6.25 13.75 4.9 15.1M15.1 15.1l-1.35-1.35M6.25 6.25 4.9 4.9"
              strokeLinecap="round"
            />
          </svg>
        </button>
        <ThemeToggle />
      </div>

      <ProviderModal
        open={providerModalOpen}
        onClose={() => {
          setProviderModalOpen(false)
          refreshHealth()
        }}
      />
    </nav>
  )
}
