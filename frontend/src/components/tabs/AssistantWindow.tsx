import { useEffect, useRef, useState } from 'react'
import { ApiError, assistantChat, pushToRedmine } from '../../api/client'
import { getSavedRedmineConfig } from '../../lib/redmineConfig'
import type {
  AssistantChatResponse,
  AssistantIssue,
  AssistantPendingAction,
  GenerationOutput,
  RedminePushResult,
} from '../../types'
import styles from './AssistantWindow.module.css'

interface ChatMessage {
  role: 'assistant' | 'user'
  content: string
  issues?: AssistantIssue[]
  issue?: AssistantIssue
  confirm?: { pendingAction: AssistantPendingAction; resolved?: 'confirmed' | 'cancelled' }
  pushResult?: RedminePushResult
}

const GREETING =
  "👋 Ask me about your Redmine issues (\"what's open in Website Redesign?\"), have me log or update one, " +
  "or just tell me what to build (\"build a backlog for a food delivery app and push it to Website Redesign\")."

// Redmine URLs saved for the API (e.g. inside Docker) may use host.docker.internal, which the
// browser can't resolve — links we open need localhost instead, same fix RedmineModal applies.
function toBrowserUrl(url: string | null | undefined): string {
  if (!url) return '#'
  return url.replace('://host.docker.internal', '://localhost')
}

/**
 * A persistent Redmine + backlog chat assistant. Unlike ChatWindow (a one-shot pre-generation
 * clarify loop that unmounts once it hands off), this conversation stays open for the session:
 * every message is routed server-side to an intent (query, create/update issue, generate a
 * backlog, push to Redmine) and this component renders whatever comes back — plain replies,
 * issue cards, a confirm/cancel prompt for mutating actions, or a push result — and hands
 * generation/push actions off to the same flows the other tabs use.
 */
export function AssistantWindow({
  lastOutput,
  genId,
  onGenerate,
  onPushed,
  onOpenRedmineModal,
}: {
  lastOutput: GenerationOutput | null
  genId: number | null
  /** Same callback ChatTab/BriefTab use to kick off generation — keeps streaming behavior identical. */
  onGenerate: (text: string) => void
  onPushed: () => void
  onOpenRedmineModal: () => void
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: 'assistant', content: GREETING }])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const transcriptRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, thinking])

  async function handleResponse(res: AssistantChatResponse) {
    setMessages((m) => [
      ...m,
      {
        role: 'assistant',
        content: res.reply,
        issues: res.issues,
        issue: res.issue,
        confirm: res.requires_confirmation && res.pending_action ? { pendingAction: res.pending_action } : undefined,
      },
    ])

    if (res.action === 'trigger_generation' && res.generation_text) {
      onGenerate(res.generation_text)
    } else if (res.action === 'trigger_push') {
      await runPush()
    }
  }

  async function runPush() {
    const cfg = getSavedRedmineConfig()
    if (!cfg.url || !cfg.key || !cfg.project) {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: "I don't have a saved Redmine connection to push into yet — open the Redmine panel once to connect and pick a project, then ask me again.",
        },
      ])
      onOpenRedmineModal()
      return
    }
    if (!lastOutput) {
      setMessages((m) => [...m, { role: 'assistant', content: 'Nothing generated yet to push.' }])
      return
    }
    setThinking(true)
    try {
      const result = await pushToRedmine({
        ...(genId ? { generation_id: genId } : { output: lastOutput }),
        redmine_url: cfg.url,
        redmine_api_key: cfg.key,
        redmine_project_id: cfg.project,
      })
      setMessages((m) => [...m, { role: 'assistant', content: 'Pushed to Redmine.', pushResult: result }])
      onPushed()
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Push failed'
      setMessages((m) => [...m, { role: 'assistant', content: `Push failed: ${message}` }])
    } finally {
      setThinking(false)
    }
  }

  async function send() {
    const text = input.trim()
    if (!text || thinking) return
    setInput('')
    const userMsg: ChatMessage = { role: 'user', content: text }
    const history = [...messages, userMsg].slice(-8).map((m) => ({ role: m.role, content: m.content }))
    setMessages((m) => [...m, userMsg])
    setThinking(true)
    try {
      const cfg = getSavedRedmineConfig()
      const res = await assistantChat({
        message: text,
        history,
        redmine_url: cfg.url,
        redmine_api_key: cfg.key,
        redmine_project_id: cfg.project,
        generation_id: genId,
      })
      await handleResponse(res)
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'server error'
      setMessages((m) => [...m, { role: 'assistant', content: `Something went wrong (${message}).` }])
    } finally {
      setThinking(false)
    }
  }

  async function confirmAction(index: number, pendingAction: AssistantPendingAction) {
    setMessages((m) =>
      m.map((msg, i) => (i === index && msg.confirm ? { ...msg, confirm: { ...msg.confirm, resolved: 'confirmed' } } : msg)),
    )
    setThinking(true)
    try {
      const cfg = getSavedRedmineConfig()
      const res = await assistantChat({
        message: '',
        history: [],
        redmine_url: cfg.url,
        redmine_api_key: cfg.key,
        redmine_project_id: cfg.project,
        generation_id: genId,
        confirm: true,
        pending_action: pendingAction,
      })
      await handleResponse(res)
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'server error'
      setMessages((m) => [...m, { role: 'assistant', content: `Couldn't complete that (${message}).` }])
    } finally {
      setThinking(false)
    }
  }

  function cancelAction(index: number) {
    setMessages((m) =>
      m.map((msg, i) => (i === index && msg.confirm ? { ...msg, confirm: { ...msg.confirm, resolved: 'cancelled' } } : msg)),
    )
  }

  function handleKeydown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <div className={`card ${styles.window}`}>
      <div className={styles.header}>
        <span className={styles.title}>🤖 Redmine assistant</span>
      </div>

      <div className={styles.transcript} ref={transcriptRef}>
        {messages.map((m, i) => (
          <div key={i} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.assistant}`}>
            {m.content}

            {m.issues && m.issues.length > 0 && (
              <div className={styles.issueList}>
                {m.issues.map((issue) => (
                  <IssueCard key={issue.id} issue={issue} />
                ))}
              </div>
            )}
            {m.issue && (
              <div className={styles.issueList}>
                <IssueCard issue={m.issue} />
              </div>
            )}

            {m.confirm && !m.confirm.resolved && (
              <div className={styles.confirmRow}>
                <button className="btn btn-primary btn-sm" onClick={() => void confirmAction(i, m.confirm!.pendingAction)}>
                  Confirm
                </button>
                <button className="btn btn-secondary btn-sm" onClick={() => cancelAction(i)}>
                  Cancel
                </button>
              </div>
            )}
            {m.confirm?.resolved === 'cancelled' && <div className={styles.resolvedNote}>Cancelled.</div>}

            {m.pushResult && (
              <div className={styles.pushResult}>
                {(m.pushResult.warnings || []).map((w, j) => (
                  <div key={j} className={styles.warnLine}>⚠ {w}</div>
                ))}
                {m.pushResult.created_issues.map((issue, j) =>
                  issue.error ? (
                    <div key={j} className={styles.errorLine}>❌ {issue.type || 'Issue'}: {issue.error}</div>
                  ) : (
                    <div key={j} className={styles.okLine}>
                      ✓ <strong>{issue.type}</strong> ({issue.display_id || issue.ai_id}) →{' '}
                      <a href={toBrowserUrl(issue.url)} target="_blank" rel="noreferrer">
                        Issue #{issue.redmine_id} ↗
                      </a>
                    </div>
                  ),
                )}
                {(m.pushResult.skipped_issues || []).map((issue, j) => (
                  <div key={`skipped-${j}`} className={styles.okLine}>
                    ↷ <strong>{issue.type}</strong> — already synced as{' '}
                    <a href={toBrowserUrl(issue.url)} target="_blank" rel="noreferrer">
                      Issue #{issue.redmine_id} ↗
                    </a>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {thinking && <div className={`${styles.msg} ${styles.assistant} ${styles.typing}`}>Thinking…</div>}
      </div>

      <div className={styles.composer}>
        <textarea
          className="textarea"
          rows={2}
          placeholder="e.g. What's open in Website Redesign? / Build a backlog for a food delivery app."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeydown}
          disabled={thinking}
        />
        <button className="btn btn-primary" onClick={() => void send()} disabled={thinking || !input.trim()}>
          Send
        </button>
      </div>
      <p className="field-hint">Redmine actions use the connection saved from the Redmine panel.</p>
    </div>
  )
}

function IssueCard({ issue }: { issue: AssistantIssue }) {
  return (
    <div className={styles.issueCard}>
      <a href={toBrowserUrl(issue.url)} target="_blank" rel="noreferrer">
        #{issue.id} {issue.subject}
      </a>
      <span className={styles.issueMeta}>
        {issue.status || 'unknown status'} · {issue.priority || 'no priority'} · {issue.assignee || 'unassigned'}
        {issue.project ? ` · ${issue.project}` : ''}
      </span>
    </div>
  )
}
