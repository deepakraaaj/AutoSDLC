const DEFAULT_TITLE = document.title

/** Ask once, lazily, at the moment it's actually relevant (starting a run
 * that's going to take minutes) — not on page load, which is the pattern
 * that gets permission prompts auto-dismissed/blocked by browsers. */
export function requestNotificationPermission(): void {
  if (!('Notification' in window)) return
  if (Notification.permission === 'default') {
    void Notification.requestPermission().catch(() => {})
  }
}

/** Flip the tab title and fire a system notification so a 5-15 minute
 * generation doesn't require babysitting the tab. Only bothers if the tab
 * is actually hidden — if you're looking right at it, you already know. */
export function notifyGenerationDone(summary: string): void {
  if (document.hidden) {
    document.title = '✅ Backlog ready'
    const restore = () => {
      document.title = DEFAULT_TITLE
      window.removeEventListener('focus', restore)
      document.removeEventListener('visibilitychange', restore)
    }
    window.addEventListener('focus', restore)
    document.addEventListener('visibilitychange', restore)
  }

  if ('Notification' in window && Notification.permission === 'granted') {
    try {
      const n = new Notification('Backlog ready', { body: summary, icon: '/favicon.svg' })
      n.onclick = () => {
        window.focus()
        n.close()
      }
    } catch {
      // Notification construction can throw in some embedded/webview contexts.
    }
  }
}
