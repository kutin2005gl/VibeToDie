import { MoreVertical } from './icons'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import styles from './PopupMenu.module.css'

export interface MenuItem {
  label: string
  icon: ReactNode
  onSelect: () => void
  danger?: boolean
  separator?: boolean // vạch ngăn phía trên mục này
}

// Nút "⋮" mở menu thả xuống; đóng khi bấm ra ngoài hoặc nhấn Esc.
export function PopupMenu({ items, label = 'Tuỳ chọn' }: { items: MenuItem[]; label?: string }) {
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

  return (
    <div ref={ref} className={styles.wrap} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <button className={styles.trigger} aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <MoreVertical size={16} />
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          {items.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              className={`${styles.item} ${it.danger ? styles.danger : ''} ${it.separator ? styles.sep : ''}`}
              onClick={() => { setOpen(false); it.onSelect() }}
            >
              {it.icon}
              <span>{it.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
