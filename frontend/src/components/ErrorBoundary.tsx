import { Component, type ReactNode } from 'react'

interface State {
  error: Error | null
}

/**
 * Without this, any uncaught render error (e.g. rendering old-shaped data
 * saved before a schema change — see TestCasesPanel's steps/test_code
 * fallback for a real instance) takes the ENTIRE app down to a blank white
 * screen with nothing in the UI to recover from, only a hard reload. A
 * render error in one card/panel shouldn't be able to do that.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error('[ErrorBoundary] Caught a render error:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div style={{ maxWidth: 560, margin: '80px auto', padding: '0 var(--space-4)' }}>
        <div className="card">
          <h2 style={{ marginBottom: 'var(--space-3)' }}>Something went wrong</h2>
          <p className="text-muted" style={{ marginBottom: 'var(--space-4)' }}>
            A part of the page hit an unexpected error and couldn't render. Reloading usually
            fixes it — if you were viewing a saved project, its data may just be in an older
            format the UI doesn't handle yet.
          </p>
          <details style={{ marginBottom: 'var(--space-4)' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
              Error details
            </summary>
            <pre
              style={{
                marginTop: 'var(--space-2)',
                padding: 'var(--space-3)',
                background: 'var(--bg-inset)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-xs)',
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
              }}
            >
              {this.state.error.message}
            </pre>
          </details>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
