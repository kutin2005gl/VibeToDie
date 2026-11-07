import type { ReactNode } from 'react'
import styles from './EmptyState.module.css'

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className={styles.wrap}>
      {icon}
      <strong>{title}</strong>
      {children}
    </div>
  )
}
