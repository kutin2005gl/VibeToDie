import { BrandMark } from '../../shell/BrandMark'
import styles from './RoomEmptyState.module.css'

export function RoomEmptyState() {
  return (
    <div className={styles.wrap}>
      <BrandMark size={44} />
      <strong>Chưa có agent trong phiên này</strong>
      {/* TODO(NOT VERIFIED): dialog thêm agent chưa có screenshot. */}
      <a href="#add" onClick={(e) => e.preventDefault()}>Thêm agent để bắt đầu.</a>
    </div>
  )
}
