import type { ReactNode } from 'react'
import styles from './PageHeader.module.css'

export function PageHeader({ title, actions }: { title: ReactNode; actions?: ReactNode }) {
  return (
    <header className={styles.header}>
      <h1>{title}</h1>
      <div className={styles.actions}>{actions}</div>
    </header>
  )
}
