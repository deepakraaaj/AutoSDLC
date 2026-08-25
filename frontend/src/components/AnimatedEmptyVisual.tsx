import styles from './AnimatedEmptyVisual.module.css'

export type EmptyVisualVariant = 'overview' | 'backlog' | 'planning' | 'connections' | 'security'

export function AnimatedEmptyVisual({ variant }: { variant: EmptyVisualVariant }) {
  return (
    <div className={`${styles.visual} ${styles[variant]}`} aria-hidden="true">
      <svg viewBox="0 0 240 150" role="img">
        <defs>
          <linearGradient id={`empty-gradient-${variant}`} x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="var(--accent)" stopOpacity=".22" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity=".04" />
          </linearGradient>
        </defs>
        <circle className={styles.orbit} cx="120" cy="75" r="57" />
        <rect className={styles.cardBack} x="57" y="29" width="126" height="92" rx="13" />
        {variant === 'overview' && <>
          <path className={styles.line} d="M78 52h54M78 66h83M78 80h70" />
          <path className={styles.spark} d="m157 42 3 7 7 3-7 3-3 7-3-7-7-3 7-3z" />
          <circle className={styles.dot} cx="84" cy="101" r="7" /><path className={styles.line} d="M99 101h55" />
        </>}
        {variant === 'backlog' && <>
          <rect className={styles.itemOne} x="76" y="47" width="88" height="15" rx="5" />
          <rect className={styles.itemTwo} x="76" y="69" width="72" height="15" rx="5" />
          <rect className={styles.itemThree} x="76" y="91" width="80" height="15" rx="5" />
          <path className={styles.check} d="m83 76 4 4 8-9" />
        </>}
        {variant === 'planning' && <>
          <path className={styles.planningGlow} d="M45 105c-8-34 19-75 65-81 49-7 96 19 91 66-4 40-44 61-89 57-31-3-60-16-67-42Z" />
          <g className={styles.board}>
            <rect className={styles.boardPanel} x="48" y="35" width="144" height="92" rx="13" />
            <rect className={styles.boardHeader} x="48" y="35" width="144" height="23" rx="13" />
            <path className={styles.headerMask} d="M48 48h144v10H48z" />
            <circle className={styles.windowDot} cx="62" cy="47" r="3" /><circle className={styles.windowDot} cx="72" cy="47" r="3" /><circle className={styles.windowDot} cx="82" cy="47" r="3" />
            <rect className={styles.sprintPill} x="139" y="43" width="39" height="8" rx="4" />
            <path className={styles.lane} d="M62 70h116M62 91h116M62 112h116" />
            <rect className={styles.storyBlue} x="69" y="64" width="43" height="13" rx="5" />
            <rect className={styles.storyViolet} x="119" y="64" width="32" height="13" rx="5" />
            <rect className={styles.storyGreen} x="82" y="85" width="51" height="13" rx="5" />
            <rect className={styles.storyAmber} x="139" y="85" width="30" height="13" rx="5" />
            <rect className={styles.storyBlue} x="65" y="106" width="36" height="13" rx="5" />
            <rect className={styles.storyViolet} x="108" y="106" width="58" height="13" rx="5" />
          </g>
          <g className={styles.capacityCard}>
            <rect x="164" y="103" width="49" height="34" rx="10" />
            <circle cx="179" cy="120" r="8" /><path d="M179 112v8l5 3" />
            <path d="M193 115h11M193 121h8M193 127h6" />
          </g>
          <g className={styles.doneBadge}>
            <circle cx="47" cy="111" r="17" /><path d="m38 111 6 6 12-14" />
          </g>
          <circle className={styles.floatDotOne} cx="207" cy="55" r="5" />
          <circle className={styles.floatDotTwo} cx="33" cy="68" r="4" />
        </>}
        {variant === 'connections' && <>
          <circle className={styles.dot} cx="89" cy="75" r="11" /><circle className={styles.dot} cx="151" cy="75" r="11" />
          <path className={styles.line} d="M100 75h40M120 75v25M108 100h24" />
        </>}
        {variant === 'security' && <>
          <path className={styles.line} d="M120 44 153 56v23c0 21-14 31-33 38-19-7-33-17-33-38V56z" />
          <path className={styles.check} d="m105 79 10 10 21-25" />
        </>}
      </svg>
    </div>
  )
}
