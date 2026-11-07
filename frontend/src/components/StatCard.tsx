import type { ReactNode } from 'react'
import styles from './StatCard.module.css'

export function StatCard({ icon, label, value, note }: { icon?: ReactNode; label: string; value: ReactNode; note?: string }) {
  return (
    <div className={styles.card}>
      <span className={styles.label}>{icon}{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  )
}
