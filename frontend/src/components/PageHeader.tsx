import styles from './PageHeader.module.css'

export function PageHeader({ title, description, compact = false }: { title: string; description?: string; compact?: boolean }) {
  return (
    <div className={`${styles.header} ${compact ? styles.compact : ''}`}>
      <h1 className={styles.title}>{title}</h1>
      {description && <p className={styles.description}>{description}</p>}
    </div>
  )
}
