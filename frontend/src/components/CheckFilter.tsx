import { ChevronDown } from './icons'
import { useEffect, useRef, useState } from 'react'
import styles from './CheckFilter.module.css'

export interface CheckOption {
  value: string
  count: number
}

// Bộ lọc dạng nút + danh sách ô tích (chọn nhiều), mỗi dòng kèm số lượng.
export function CheckFilter({ label, options, selected, onChange }: {
  label: string
  options: CheckOption[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = (v: string) => onChange(selected.includes(v) ? selected.filter((s) => s !== v) : [...selected, v])

  return (
    <div ref={ref} className={styles.wrap}>
      <button
        className={`${styles.btn} ${selected.length ? styles.active : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {label}{selected.length > 0 && <span className={styles.badge}>{selected.length}</span>}
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className={styles.menu} role="listbox" aria-multiselectable="true">
          {options.map((o) => (
            <label key={o.value} className={styles.item}>
              <input type="checkbox" checked={selected.includes(o.value)} onChange={() => toggle(o.value)} />
              <span className={styles.name}>{o.value}</span>
              <span className={styles.count}>{o.count}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
