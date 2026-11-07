'use client'

import { useState } from 'react'
import { ChevronRight } from '../../components/icons'
import type { Analytics } from '../../api/admin'
import styles from './Analytics.module.css'

// TODO(NOT VERIFIED): nội dung accordion khi mở chưa có screenshot; bảng dưới là đề xuất.
export function PerAgentSummary({ rows }: { rows: Analytics['per_agent'] }) {
  const [open, setOpen] = useState(false)
  return (
    <section className={styles.chartCard}>
      <button className={styles.accordion} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ChevronRight size={14} className={open ? styles.rot : ''} />
        <span>Tổng hợp theo agent</span>
        <b>{rows.length}</b>
      </button>
      {open && (
        <table className={styles.table}>
          <thead><tr><th>Agent</th><th className={styles.num}>Gọi model</th><th className={styles.num}>Gọi công cụ</th><th className={styles.num}>Lỗi</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.agent}><td>{r.agent}</td><td className={styles.num}>{r.llm_calls}</td><td className={styles.num}>{r.tool_calls}</td><td className={styles.num}>{r.errors}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
