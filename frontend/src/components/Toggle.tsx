import styles from './Toggle.module.css'

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className={styles.wrap}>
      <span>{label}</span>
      <button role="switch" aria-checked={checked} className={`${styles.track} ${checked ? styles.on : ''}`} onClick={() => onChange(!checked)}>
        <i />
      </button>
    </label>
  )
}
