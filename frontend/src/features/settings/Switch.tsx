import styles from './Switch.module.css'

// Công tắc trần (không kèm nhãn) dùng ở các dòng cài đặt.
export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`${styles.track} ${checked ? styles.on : ''}`}
      onClick={() => onChange(!checked)}
    >
      <i />
    </button>
  )
}
