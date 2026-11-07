import type { ReactNode } from 'react'
import { Search } from './icons'
import styles from './SearchBar.module.css'

interface Props {
  value: string
  onChange: (v: string) => void
  placeholder: string
  filters?: ReactNode
}

export function SearchBar({ value, onChange, placeholder, filters }: Props) {
  return (
    <div className={styles.row}>
      <label className={styles.input}>
        <Search size={14} />
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      </label>
      {filters}
    </div>
  )
}

export function FilterSelect({ label, options, value, onChange }: { label: string; options: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <select className={styles.filter} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  )
}
