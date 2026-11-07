import { ChevronDown } from '../../components/icons'
import styles from './Select.module.css'

// Ô chọn dạng dropdown dùng chung cho các trang Cài đặt (width mặc định theo nội dung).
export function Select({ value, options, onChange, label, width }: {
  value: string
  options: string[]
  onChange: (v: string) => void
  label: string
  width?: number
}) {
  return (
    <span className={styles.select} style={width ? { width } : undefined}>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
      <ChevronDown size={14} />
    </span>
  )
}
