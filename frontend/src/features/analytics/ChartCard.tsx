import type { ReactNode } from 'react'
import styles from './Analytics.module.css'

// Màu lấy từ token của theme (SVG của Recharts nhận được var()).
export const axisStyle = { fill: 'var(--text-muted)', fontSize: 11 }
export const tooltipStyle = {
  contentStyle: { background: 'var(--bg-raised)', border: '1px solid var(--border-subtle)', borderRadius: 6, fontSize: 12 },
  labelStyle: { color: 'var(--text-primary)' },
  cursor: { fill: 'var(--hover-tint)' },
}

export function ChartCard({ title, children, legend }: { title: string; children: ReactNode; legend?: ReactNode }) {
  return (
    <section className={styles.chartCard}>
      <h3>{title}</h3>
      {children}
      {legend}
    </section>
  )
}

export interface LegendItem { id: string; label: string; color: string }

// Legend: bấm để ẩn/hiện series (INFERRED từ ảnh; hành vi thật NOT VERIFIED).
export function SeriesLegend({ items, hidden, onToggle }: { items: LegendItem[]; hidden: Set<string>; onToggle: (id: string) => void }) {
  return (
    <ul className={styles.legend}>
      {items.map((i) => (
        <li key={i.id}>
          <button className={hidden.has(i.id) ? styles.legendOff : ''} onClick={() => onToggle(i.id)}>
            <i style={{ background: i.color }} />{i.label}
          </button>
        </li>
      ))}
    </ul>
  )
}
