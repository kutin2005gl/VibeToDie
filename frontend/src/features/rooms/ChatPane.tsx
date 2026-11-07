import { useEffect, useRef, useState } from 'react'
import { ExternalLink, FileText, Filter, Folder, MoreVertical, Users } from '../../components/icons'
import { MessageCard } from './MessageCard'
import { Composer } from './Composer'
import { RoomEmptyState } from './RoomEmptyState'
import { currentUser, type MockMessage, type MockRoom } from '../../mocks/rooms'
import styles from './ChatPane.module.css'

interface Props {
  room: MockRoom
  participantsOpen: boolean
  onToggleParticipants: () => void
  onSend: (msg: MockMessage) => void
}

type Mode = 'work' | 'chat'

export function ChatPane({ room, participantsOpen, onToggleParticipants, onSend }: Props) {
  const [mode, setMode] = useState<Mode>('chat')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [room.id, room.messages.length])

  return (
    <section className={styles.pane}>
      <header className={styles.header}>
        <div className={styles.mode} role="tablist">
          <button role="tab" aria-selected={mode === 'work'} className={mode === 'work' ? styles.on : ''} onClick={() => setMode('work')}>Việc</button>
          <button role="tab" aria-selected={mode === 'chat'} className={mode === 'chat' ? styles.on : ''} onClick={() => setMode('chat')}>Chat</button>
        </div>
        <h2>{room.title}</h2>
        {/* TODO(NOT VERIFIED): hành vi các icon header chưa có screenshot; chỉ riêng nút participants có toggle. */}
        <div className={styles.icons}>
          <button aria-label="Lọc tin"><Filter size={16} /></button>
          <button aria-label="Người tham gia" className={participantsOpen ? styles.on : ''} onClick={onToggleParticipants}>
            <Users size={16} /> {room.agentIds.length + 1}
          </button>
          <button aria-label="Hồ sơ khách/đơn"><Folder size={16} /></button>
          <button aria-label="Tài liệu"><FileText size={16} /></button>
          <button aria-label="Mở cửa sổ riêng"><ExternalLink size={16} /></button>
          <button aria-label="Tuỳ chọn"><MoreVertical size={16} /></button>
        </div>
      </header>

      {mode === 'work' ? (
        // TODO(NOT VERIFIED): chế độ Work của Band chưa có screenshot. Đề xuất: bảng việc (tra kho → báo giá → chốt đơn).
        <div className={styles.center}>
          <p>Chế độ "Việc" chưa được thiết kế (thiếu screenshot).</p>
        </div>
      ) : room.messages.length === 0 ? (
        <RoomEmptyState />
      ) : (
        <div className={styles.messages}>
          {room.messages.map((m) => <MessageCard key={m.id} message={m} />)}
          <div ref={endRef} />
        </div>
      )}

      <Composer
        onSend={(body) =>
          onSend({ id: `m${Date.now()}`, authorId: currentUser.id, kind: 'text', body, time: new Date().toTimeString().slice(0, 5) })
        }
      />
    </section>
  )
}
