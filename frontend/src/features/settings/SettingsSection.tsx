import type { ReactNode } from 'react'
import styles from './SettingsSection.module.css'

// Khung chung cho mọi tab Cài đặt: cột giữa có tiêu đề và đường kẻ.
export function SettingsSection({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className={styles.section}>
      <h1 className={styles.title}>{title}</h1>
      {children}
    </section>
  )
}

export function SettingsRow({ title, description, action }: { title: ReactNode; description?: ReactNode; action: ReactNode }) {
  return (
    <div className={styles.row}>
      <div className={styles.text}>
        <div className={styles.rowTitle}>{title}</div>
        {description && <div className={styles.rowDesc}>{description}</div>}
      </div>
      <div className={styles.action}>{action}</div>
    </div>
  )
}
