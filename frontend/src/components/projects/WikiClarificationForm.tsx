import { useState } from 'react'
import type { WikiClarificationQuestion } from '../../types'
import styles from './WikiSection.module.css'

export function WikiClarificationForm({ questions, submitting, onSubmit }: {
  questions: WikiClarificationQuestion[]
  submitting: boolean
  onSubmit: (answers: Record<string, string>) => void
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const complete = questions.every((item) => answers[item.id]?.trim())
  return <div className={styles.clarification} role="region" aria-label="Wiki clarification required">
    <h3>Clarification needed</h3>
    <p>The repository does not explain this business context. Answer these before the wiki is generated.</p>
    {questions.map((item) => <label key={item.id}>
      <span>{item.question}</span>
      <small>{item.why}</small>
      <textarea rows={3} value={answers[item.id] || ''} onChange={(event) => setAnswers({ ...answers, [item.id]: event.target.value })} />
    </label>)}
    <button className="btn btn-primary" disabled={!complete || submitting} onClick={() => onSubmit(answers)}>
      {submitting ? 'Generating…' : 'Continue generation'}
    </button>
  </div>
}
