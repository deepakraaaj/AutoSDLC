import { useState } from 'react'
import { ApiError, assistantChat } from '../../api/client'
import { getSavedRedmineConfig } from '../../lib/redmineConfig'
import type { AssistantChatResponse, AssistantPendingAction } from '../../types'
import styles from './ChangeRequestChat.module.css'

interface Message {
  role: 'assistant' | 'user'
  content: string
  confirm?: { pendingAction: AssistantPendingAction; resolved?: 'confirmed' | 'cancelled' }
}

const GREETING = 'Tell me what to change — e.g. "add a note about rate limiting to the login story" or "rename EP-0003".'

/**
 * The "interrupt and change anything" mechanism this whole visualizer exists for, alongside
 * clicking items directly: a compact confirm/cancel chat, embedded here rather than built as a
 * new component from scratch — it's the same transcript/confirm/cancel shape AssistantWindow
 * already renders for create/update_issue, aimed at the same /assistant/chat endpoint, just
 * without the issue-card/push-result rendering that intent never produces. Whatever intent the
 * router actually picks (usually change_request here, but nothing stops a stray Redmine question
 * from working too) is handled identically — Python decides, this just renders the result.
 */
export function ChangeRequestChat({ genId, onChanged }: { genId: number | null; onChanged: () => void }) {
  const [messages, setMessages] = useState<Message[]>([{ role: 'assistant', content: GREETING }])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)

  function appendReply(res: AssistantChatResponse) {
    setMessages((m) => [
      ...m,
      {
        role: 'assistant',
        content: res.reply,
        confirm: res.requires_confirmation && res.pending_action ? { pendingAction: res.pending_action } : undefined,
      },
    ])
  }

  async function send() {
    const text = input.trim()
    if (!text || thinking) return
    setInput('')
    const userMsg: Message = { role: 'user', content: text }
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
      appendReply(res)
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
      appendReply(res)
      if (pendingAction.intent === 'change_request') onChanged()
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
    <div className={styles.wrap}>
      <div className={styles.header}>💬 Change request</div>
      <div className={styles.transcript}>
        {messages.map((m, i) => (
          <div key={i} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.assistant}`}>
            {m.content}
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
          </div>
        ))}
        {thinking && <div className={`${styles.msg} ${styles.assistant} ${styles.typing}`}>Thinking…</div>}
      </div>
      <div className={styles.composer}>
        <textarea
          className="textarea"
          rows={2}
          placeholder='e.g. "Add a note about rate limiting to the login story"'
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeydown}
          disabled={thinking}
        />
        <button className="btn btn-primary btn-sm" onClick={() => void send()} disabled={thinking || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  )
}
