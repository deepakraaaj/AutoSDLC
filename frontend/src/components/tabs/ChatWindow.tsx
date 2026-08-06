import { useEffect, useRef, useState } from 'react'
import { ApiError, clarifyChat } from '../../api/client'
import type { ClarifyingQuestion } from '../../types'
import styles from './ChatWindow.module.css'

interface QAEntry {
  question: string
  answer: string
}

interface ChatMessage {
  role: 'assistant' | 'user'
  content: string
  why?: string[]
}

const GREETING =
  "👋 Tell me about the project you want to build — a sentence or two is fine to start. I'll ask a couple of quick questions if I need more detail, then generate your backlog."

/**
 * A persistent conversation, not a form-then-reveal-a-panel: the greeting
 * shows the instant this mounts, the user's first message *is* the project
 * idea, and the assistant keeps asking follow-ups (via /clarify-chat, capped
 * server-side so it always terminates) until it's satisfied or the user
 * hits Skip. On completion, calls onReady with the brief text enriched with
 * whatever Q&A happened.
 */
export function ChatWindow({
  onReady,
  disabled = false,
  initialText = '',
}: {
  onReady: (enrichedText: string) => void
  disabled?: boolean
  initialText?: string
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: 'assistant', content: GREETING }])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const [showSkip, setShowSkip] = useState(false)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const stateRef = useRef<{
    originalText: string
    qaHistory: QAEntry[]
    pendingQuestions: ClarifyingQuestion[]
  } | null>(null)

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, thinking])

  useEffect(() => {
    if (!initialText.trim() || stateRef.current) return
    stateRef.current = { originalText: initialText.trim(), qaHistory: [], pendingQuestions: [] }
    setMessages((m) => [...m, { role: 'user', content: 'Brief loaded. Please check whether you need any clarification before generating.' }])
    setShowSkip(true)
    void requestRound()
    // Seed only once for this mounted conversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function finish() {
    const st = stateRef.current
    if (!st) return
    let enriched = st.originalText
    if (st.qaHistory.length) {
      const qaText = st.qaHistory.map((qa) => `- Q: ${qa.question}\n  A: ${qa.answer}`).join('\n')
      enriched = `${st.originalText}\n\nClarifications:\n${qaText}`
    }
    stateRef.current = null
    setShowSkip(false)
    onReady(enriched)
  }

  async function requestRound() {
    setThinking(true)
    try {
      const st = stateRef.current
      if (!st) return
      const data = await clarifyChat(st.originalText, st.qaHistory)
      if (data.needs_clarification && data.questions.length) {
        st.pendingQuestions = data.questions
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            content: data.questions.map((q) => q.question).join('\n'),
            why: data.questions.map((q) => q.why_it_matters).filter(Boolean),
          },
        ])
      } else {
        setMessages((m) => [...m, { role: 'assistant', content: "Got it — that's enough detail. Generating your backlog now…" }])
        finish()
      }
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'server error'
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: `Couldn't check clarity (${message}). You can skip and generate anyway.` },
      ])
    } finally {
      setThinking(false)
    }
  }

  async function send() {
    const text = input.trim()
    if (!text || thinking || disabled) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: text }])

    if (!stateRef.current) {
      stateRef.current = { originalText: text, qaHistory: [], pendingQuestions: [] }
      setShowSkip(true)
    } else {
      const questionText = stateRef.current.pendingQuestions.map((q) => q.question).join(' / ')
      stateRef.current.qaHistory.push({ question: questionText, answer: text })
    }
    await requestRound()
  }

  function skip() {
    if (!stateRef.current) return
    finish()
  }

  function handleKeydown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  const composerDisabled = disabled || thinking

  return (
    <div className={`card ${styles.window}`}>
      <div className={styles.header}>
        <span className={styles.title}>💬 Describe your project</span>
        {showSkip && (
          <button className="btn btn-secondary btn-sm" onClick={skip} disabled={disabled}>
            Skip — generate now
          </button>
        )}
      </div>

      <div className={styles.transcript} ref={transcriptRef}>
        {messages.map((m, i) => (
          <div key={i} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.assistant}`}>
            {m.content}
            {m.why?.map((w, j) => (
              <div key={j} className={styles.why}>
                {w}
              </div>
            ))}
          </div>
        ))}
        {thinking && (
          <div className={`${styles.msg} ${styles.assistant} ${styles.typing}`}>Thinking…</div>
        )}
      </div>

      <div className={styles.composer}>
        <textarea
          className="textarea"
          rows={2}
          placeholder="e.g. Build a food delivery app for small restaurants."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeydown}
          disabled={composerDisabled}
        />
        <button className="btn btn-primary" onClick={send} disabled={composerDisabled || !input.trim()}>
          Send
        </button>
      </div>
      <p className="field-hint">Use Brief for reusable Markdown. Use Chat for a fast one-off.</p>
    </div>
  )
}
