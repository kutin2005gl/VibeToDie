import { ChevronDown, Folder, FolderPlus } from '../../components/icons'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useDismiss } from '../../components/useDismiss'
import styles from './Pickers.module.css'

// Dropdown "Thư mục": chọn nơi phiên mới sẽ được đưa vào, hoặc tạo thư mục mới.
// TODO: thư mục chỉ giữ trong phiên và chưa gửi lên API.
export function FolderPicker({ folders, value, onCreate, onChange }: {
  folders: string[]
  value: string | null
  onCreate: (name: string) => void
  onChange: (name: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const close = useCallback(() => setOpen(false), [])
  useDismiss(open, ref, close)

  useEffect(() => {
    if (open) inputRef.current?.focus()
    else setName('')
  }, [open])

  const create = () => {
    const n = name.trim()
    if (!n) return
    if (!folders.includes(n)) onCreate(n)
    onChange(n)
    setOpen(false)
  }

  return (
    <div ref={ref} className={styles.wrap}>
      <button className={`${styles.trigger} ${open ? styles.open : ''}`} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Folder size={14} />
        <span>{value ?? 'Thư mục'}</span>
        <ChevronDown size={13} />
      </button>
      {open && (
        <div className={`${styles.panel} ${styles.folderPanel}`} role="dialog" aria-label="Chọn thư mục">
          <div className={styles.section}>Đưa vào</div>
          {folders.length === 0 && <p className={styles.plain}>Chưa có thư mục nào.</p>}
          {folders.map((f) => (
            <button key={f} className={`${styles.folderRow} ${f === value ? styles.picked : ''}`} onClick={() => { onChange(f === value ? null : f); setOpen(false) }}>
              <Folder size={14} />{f}
            </button>
          ))}
          <div className={styles.section}>Thư mục mới</div>
          <label className={styles.newFolder}>
            <FolderPlus size={14} />
            <input
              ref={inputRef}
              value={name}
              maxLength={40}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); create() } }}
              placeholder="Nhập tên thư mục"
            />
          </label>
        </div>
      )}
    </div>
  )
}
