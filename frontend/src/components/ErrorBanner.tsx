import styles from './ErrorBanner.module.css'

export function ErrorBanner({ message, userAction }: { message: string; userAction?: string | null }) {
  return (
    <div className={styles.box} role="alert">
      <span>Error: {message}</span>
      {userAction && <span className={styles.hint}>{userAction}</span>}
    </div>
  )
}
