import { FolderPlus, Filter, SquarePen, PanelLeftClose, Plus } from '../../components/icons'
import { AvatarStack } from '../../components/Avatar'
import { agentById } from '../../mocks/agents'
import type { MockRoom } from '../../mocks/rooms'
import styles from './RoomList.module.css'

interface Props {
  rooms: MockRoom[]
  activeId: string
  onSelect: (id: string) => void
}

// TODO(NOT VERIFIED): chức năng chính xác của 4 icon công cụ (INFERRED theo icon: thư mục, lọc, tạo mới, thu gọn).
export function RoomList({ rooms, activeId, onSelect }: Props) {
  return (
    <section className={styles.list}>
      <header>
        <span>Phiên làm việc</span>
        <button aria-label="Tạo phiên"><Plus size={14} /></button>
        <div className={styles.tools}>
          <button aria-label="Thư mục mới"><FolderPlus size={15} /></button>
          <button aria-label="Lọc"><Filter size={15} /></button>
          <button aria-label="Soạn mới"><SquarePen size={15} /></button>
          <button aria-label="Thu gọn"><PanelLeftClose size={15} /></button>
        </div>
      </header>
      <ul>
        {rooms.map((r) => (
          <li key={r.id}>
            <button className={`${styles.item} ${r.id === activeId ? styles.active : ''}`} onClick={() => onSelect(r.id)}>
              <strong>{r.title}</strong>
              <span className={styles.sub}>
                {r.agentIds.length > 0 && <AvatarStack agents={r.agentIds.map(agentById)} max={3} size={18} />}
                <small>{r.updated}</small>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
