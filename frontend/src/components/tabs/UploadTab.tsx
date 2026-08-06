import { useRef, useState } from 'react'
import styles from './UploadTab.module.css'

function isSupportedUploadFile(file: File | null | undefined): boolean {
  return !!file && /\.(md|docx)$/i.test(file.name || '')
}

export function UploadTab({
  isGenerating,
  onSubmit,
}: {
  isGenerating: boolean
  onSubmit: (file: File) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function acceptFile(f: File | null | undefined) {
    if (!isSupportedUploadFile(f)) {
      setFile(null)
      setError(f ? 'Unsupported file type. Use .md or .docx' : null)
      return
    }
    setFile(f!)
    setError(null)
  }

  return (
    <div>
      <div className="card">
        <label className="field-label">Upload Markdown or Word</label>
        <div
          className={`${styles.zone} ${dragOver ? styles.dragOver : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            acceptFile(e.dataTransfer.files[0])
          }}
        >
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-secondary)" strokeWidth="1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <p>
            <strong>Click to upload</strong> or drag and drop
          </p>
          <p className="text-muted">Markdown or Word files only (.md, .docx)</p>
          {file && <div className={styles.fileName}>{file.name}</div>}
          {error && <div className={styles.error}>{error}</div>}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".md,.docx"
          className={styles.hiddenInput}
          onChange={(e) => acceptFile(e.target.files?.[0])}
        />
        <button
          className="btn btn-success btn-block"
          style={{ marginTop: 'var(--space-3)' }}
          disabled={!file || isGenerating}
          onClick={() => file && onSubmit(file)}
        >
          Generate backlog
        </button>
        <p className="field-hint">No brief yet? Build one in Brief.</p>
      </div>
    </div>
  )
}
