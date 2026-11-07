import logo from '../assets/boa-logo.png'
import { Bot } from '../components/icons'
import styles from './BrandMark.module.css'

// Biểu tượng BOA: khuôn mặt cười đeo tai nghe lấy từ chữ O của logo (cùng hình với icon Bot).
export function BrandMark({ size = 16 }: { size?: number }) {
  return <Bot size={size} />
}

// Logo chữ BOA đầy đủ (ảnh do chủ dự án cung cấp), tô bằng màu chữ hiện tại qua mask.
export function BrandLogo({ height = 28 }: { height?: number }) {
  return (
    <span
      role="img"
      aria-label="BOA"
      className={styles.logo}
      style={{ height, width: (height * 670) / 392, maskImage: `url(${logo.src})`, WebkitMaskImage: `url(${logo.src})` }}
    />
  )
}
