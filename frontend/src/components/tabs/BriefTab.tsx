import { useEffect, useMemo, useRef, useState } from 'react'
import { getBriefResources, validateBrief } from '../../api/client'
import { briefContentLooksLikePrompt, briefFilenameFromContent, detectTemplateType } from '../../lib/briefDetection'
import styles from './BriefTab.module.css'

type StatusTone = '' | 'success' | 'warning' | 'error'

export function BriefTab({ isGenerating, onSubmit }: { isGenerating: boolean; onSubmit: (text: string) => void }) {
  const [resources, setResources] = useState<Record<string, string>>({})
  const [text, setText] = useState('')
  const [status, setStatus] = useState<{ message: string; tone: StatusTone }>({ message: '', tone: '' })
  const [showTemplateWarning, setShowTemplateWarning] = useState(false)
  const [validatorIssues, setValidatorIssues] = useState<string[] | null>(null)
  const [templateSuggestion, setTemplateSuggestion] = useState<string | null>(null)
  const [checkingBrief, setCheckingBrief] = useState(false)
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const pendingTextRef = useRef<string | null>(null)

  useEffect(() => {
    getBriefResources()
      .then((data) => {
        setResources(data.resources || {})
        if (!text.trim()) {
          const template = data.resources?.project_template
          if (template) {
            setText(template)
            setStatus({ message: 'Template loaded. Edit for your project.', tone: 'success' })
            setShowTemplateWarning(true)
          }
        }
      })
      .catch(() => {
        setStatus({ message: 'Brief assets failed to load. Template and prompt guides are unavailable.', tone: 'error' })
      })
    // Load once on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const looksLikePrompt = briefContentLooksLikePrompt(text)
  const trimmed = text.trim()

  useEffect(() => {
    if (trimmed.length > 200) {
      const detected = detectTemplateType(text)
      setTemplateSuggestion(detected.type !== 'structured_brief' ? detected.label : null)
    } else {
      setTemplateSuggestion(null)
    }
    // Only re-run when the trimmed text meaningfully changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trimmed])

  const hint = useMemo(() => {
    if (!trimmed) return { text: 'Paste a finished brief or load the template.', tone: '' as StatusTone }
    if (looksLikePrompt) return { text: 'Prompt detected. Run it in an AI tool first.', tone: 'warning' as StatusTone }
    return { text: 'Brief ready. Generate or download it.', tone: '' as StatusTone }
  }, [trimmed, looksLikePrompt])

  function loadTemplate() {
    const template = resources.project_template
    if (!template) {
      setStatus({ message: 'Template unavailable.', tone: 'error' })
      return
    }
    setText(template)
    setStatus({ message: 'Template loaded. Edit for your project.', tone: 'success' })
    setShowTemplateWarning(true)
    editorRef.current?.focus()
  }

  function copyBrief() {
    if (!trimmed) return
    void navigator.clipboard.writeText(trimmed)
    setStatus({ message: 'Copied.', tone: 'success' })
  }

  function downloadBrief() {
    if (!trimmed) return
    const blob = new Blob([trimmed], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const filename = briefFilenameFromContent(trimmed)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    setStatus({ message: `Downloaded ${filename}.`, tone: 'success' })
  }

  async function handleGenerateClick() {
    if (briefContentLooksLikePrompt(trimmed)) {
      setStatus({ message: 'Prompt detected. Run it in an AI tool first.', tone: 'warning' })
      return
    }
    setValidatorIssues(null)
    setStatus({ message: 'Checking brief…', tone: '' })
    setCheckingBrief(true)
    try {
      const validation = await validateBrief(trimmed)
      if (validation.score !== 'strong') {
        pendingTextRef.current = trimmed
        setValidatorIssues(validation.suggestions || [])
        setStatus({ message: 'Review the suggestions below before generating.', tone: 'warning' })
        return
      }
    } catch {
      // If validation itself fails, don't block generation on it.
    } finally {
      setCheckingBrief(false)
    }
    setStatus({ message: '', tone: '' })
    onSubmit(trimmed)
  }

  function continueAnyway() {
    setValidatorIssues(null)
    if (pendingTextRef.current) onSubmit(pendingTextRef.current)
    pendingTextRef.current = null
  }

  const generateDisabled = isGenerating || !trimmed || looksLikePrompt || checkingBrief

  return (
    <div>
      <div className={`card ${styles.card}`}>
        {/* Visually hidden — the page header above already says "Brief";
            this just keeps the textarea labeled for screen readers. */}
        <label className="sr-only" htmlFor="brief-editor">
          Brief
        </label>
        <textarea
          id="brief-editor"
          ref={editorRef}
          className={`textarea ${styles.editor}`}
          spellCheck={false}
          placeholder="Loading brief assets..."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className={styles.toolbar}>
          {/* Template/Copy/Download are utility actions — all secondary, so
              "Generate backlog" is the only loud button on the page and
              reads unambiguously as the primary action. */}
          <button className="btn btn-secondary" onClick={loadTemplate}>
            Template
          </button>
          <button className="btn btn-secondary" onClick={copyBrief} disabled={!trimmed}>
            Copy
          </button>
          <button className="btn btn-secondary" onClick={downloadBrief} disabled={!trimmed}>
            Download
          </button>
          <button className="btn btn-success" onClick={handleGenerateClick} disabled={generateDisabled}>
            Generate backlog
          </button>
        </div>
        {/* One status line, not two saying almost the same thing — the
            specific, timely message (status) wins over the generic hint. */}
        <div className={`field-hint ${(status.message ? status.tone : hint.tone) ? `tone-${status.message ? status.tone : hint.tone}` : ''}`}>
          {status.message || hint.text}
        </div>

        {showTemplateWarning && (
          <div className={styles.warningBanner}>
            <span aria-hidden="true">⚠️</span>
            <div>
              <strong>This is a filled-in EXAMPLE</strong>
              <p>Edit the project name, goals, features, and other details for YOUR project before generating.</p>
            </div>
            <button className={styles.warningClose} onClick={() => setShowTemplateWarning(false)} aria-label="Dismiss">
              ✕
            </button>
          </div>
        )}

        {validatorIssues && (
          <div className={styles.validator}>
            <div className={styles.validatorTitle}>Brief has some gaps</div>
            <div className={styles.validatorList}>
              {validatorIssues.map((issue, i) => (
                <div key={i} className={styles.validatorItem}>
                  <span className={styles.validatorIcon}>✕</span>
                  <span>{issue}</span>
                </div>
              ))}
            </div>
            <div className={styles.validatorActions}>
              <button className="btn btn-success btn-sm" onClick={continueAnyway}>
                Continue anyway
              </button>
              <button className="btn btn-secondary btn-sm" onClick={() => setValidatorIssues(null)}>
                Keep editing
              </button>
            </div>
          </div>
        )}

        {templateSuggestion && (
          <div className={styles.suggestion}>
            <div className={styles.suggestionHeader}>
              <div>
                <div className={styles.suggestionTitle}>Detected format — suggested template</div>
                <div className={styles.suggestionDetected}>Detected: {templateSuggestion}</div>
              </div>
              <button
                className={styles.warningClose}
                onClick={() => setTemplateSuggestion(null)}
                aria-label="Dismiss"
              >
                ✕
              </button>
            </div>
            <button
              className={styles.suggestionBtn}
              onClick={() => {
                loadTemplate()
                setTemplateSuggestion(null)
              }}
            >
              <div className={styles.suggestionBtnName}>Project Brief Template</div>
              <div className={styles.suggestionBtnDesc}>Start fresh with the structured template</div>
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
