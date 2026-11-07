import { useState } from 'react'
import { useStore } from '../../shell/store'
import { RoomList } from './RoomList'
import { ChatPane } from './ChatPane'
import { ParticipantsPanel } from './ParticipantsPanel'
import type { MockMessage } from '../../mocks/rooms'
import styles from './RoomsPage.module.css'

// TODO(NOT VERIFIED): splitter kéo đổi kích thước cột (chỉ INFERRED từ đường kẻ dày trong ảnh) — chưa làm.
export function RoomsPage() {
  const { rooms, activeRoomId, setActiveRoomId, appendMessage } = useStore()
  const [showParticipants, setShowParticipants] = useState(true)
  const room = rooms.find((r) => r.id === activeRoomId) ?? rooms[0]

  const send = (msg: MockMessage) => appendMessage(room.id, msg)

  return (
    <div className={styles.page}>
      <RoomList rooms={rooms} activeId={room.id} onSelect={setActiveRoomId} />
      <ChatPane
        room={room}
        participantsOpen={showParticipants}
        onToggleParticipants={() => setShowParticipants((s) => !s)}
        onSend={send}
      />
      {showParticipants && <ParticipantsPanel room={room} onClose={() => setShowParticipants(false)} />}
    </div>
  )
}
