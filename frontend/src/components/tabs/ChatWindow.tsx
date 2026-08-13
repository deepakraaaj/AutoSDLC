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

// Shown right after each answer, before the next question — a plain client-
// side reaction (no extra LLM call) so answering a question reads as a
// reply getting acknowledged, not a form field advancing to the next one.
const ACKNOWLEDGMENTS = ['Got it.', 'Noted.', 'Thanks, got it.', 'Okay, noted.']
function randomAcknowledgment(): string {
  return ACKNOWLEDGMENTS[Math.floor(Math.random() * ACKNOWLEDGMENTS.length)]
}

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
    /** The question currently displayed and awaiting its own answer. */
    currentQuestion: ClarifyingQuestion | null
    /** Rest of this round's questions, not yet shown — revealed one at a
     * time as each prior one gets answered, instead of dumping the whole
     * round in one message and expecting a single combined reply. */
    questionQueue: ClarifyingQuestion[]
  } | null>(null)

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, thinking])

  useEffect(() => {
    if (!initialText.trim() || stateRef.current) return
    stateRef.current = { originalText: initialText.trim(), qaHistory: [], currentQuestion: null, questionQueue: [] }
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

  /** Reveals the next queued question as its own assistant message — this is
   * what makes multi-question rounds feel like one-at-a-time conversation
   * instead of a single message dumping every question at once. Doesn't
   * call the backend; the whole round's questions already came back from
   * one /clarify-chat call, we're just pacing how they're shown. */
  function showNextQuestion() {
    const st = stateRef.current
    if (!st) return
    const [next, ...rest] = st.questionQueue
    st.currentQuestion = next
    st.questionQueue = rest
    setMessages((m) => [
      ...m,
      { role: 'assistant', content: next.question, why: next.why_it_matters ? [next.why_it_matters] : [] },
    ])
  }

  async function requestRound() {
    setThinking(true)
    try {
      const st = stateRef.current
      if (!st) return
      const data = await clarifyChat(st.originalText, st.qaHistory)
      if (data.needs_clarification && data.questions.length) {
        st.questionQueue = data.questions
        showNextQuestion()
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
      stateRef.current = { originalText: text, qaHistory: [], currentQuestion: null, questionQueue: [] }
      setShowSkip(true)
      await requestRound()
      return
    }

    const st = stateRef.current
    if (st.currentQuestion) {
      st.qaHistory.push({ question: st.currentQuestion.question, answer: text })
      st.currentQuestion = null
      setMessages((m) => [...m, { role: 'assistant', content: randomAcknowledgment() }])
    }
    if (st.questionQueue.length > 0) {
      // More questions from this same round already in hand — show the next
      // one directly, no need to call the backend again for it.
      showNextQuestion()
    } else {
      await requestRound()
    }
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
