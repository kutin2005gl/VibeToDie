import { Check, ChevronDown } from './icons'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import styles from './ListSelect.module.css'

export interface ListOption {
  value: string
  label: string
}

// Dropdown chọn một mục: nút hiện nhãn đang chọn, danh sách có dấu ✓ ở mục đã chọn.
export function ListSelect({ value, options, onChange, label, align = 'left', placement = 'down', ghost = false, icon }: {
  value: string
  options: ListOption[]
  onChange: (v: string) => void
  label: string
  align?: 'left' | 'right'
  placement?: 'down' | 'up' // hướng mở danh sách
  ghost?: boolean // nút không viền/nền, gọn (dùng trong thẻ)
  icon?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = options.find((o) => o.value === value) ?? options[0]

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

  return (
    <div ref={ref} className={styles.wrap}>
      <button className={`${styles.btn} ${ghost ? styles.ghost : ''}`} aria-label={label} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {icon}
        <span>{current.label}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <ul className={`${styles.menu} ${align === 'right' ? styles.right : ''} ${placement === 'up' ? styles.up : ''}`} role="listbox">
          {options.map((o) => (
            <li key={o.value} role="option" aria-selected={o.value === value}>
              <button
                className={`${styles.item} ${o.value === value ? styles.selected : ''}`}
                onClick={() => { onChange(o.value); setOpen(false) }}
              >
                <span>{o.label}</span>
                {o.value === value && <Check size={14} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
