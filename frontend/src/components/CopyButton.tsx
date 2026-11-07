import { Check, Copy } from './icons'
import { useState } from 'react'
import styles from './CopyButton.module.css'

// Icon sao chép nhỏ; đổi thành dấu ✓ trong giây lát sau khi chép.
export function CopyButton({ value, label = 'Sao chép' }: { value: string; label?: string }) {
  const [done, setDone] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setDone(true)
      setTimeout(() => setDone(false), 1200)
    } catch {
      // Clipboard có thể bị chặn (webview/không có quyền); bỏ qua im lặng.
    }
  }

  return (
    <button className={styles.btn} aria-label={label} title={label} onClick={(e) => { e.stopPropagation(); void copy() }}>
      {done ? <Check size={12} strokeWidth={2} /> : <Copy size={12} />}
    </button>
  )
}
