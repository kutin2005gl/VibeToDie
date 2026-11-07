import { Crown, Plus, X } from '../../components/icons'
import { agentById } from '../../mocks/agents'
import { currentUser, type MockRoom } from '../../mocks/rooms'
import { initials, useSession } from '../../shell/session'
import styles from './ParticipantsPanel.module.css'

// TODO(NOT VERIFIED): nhóm "Agents" trong panel của Band chưa có screenshot; nhóm này là đề xuất.
export function ParticipantsPanel({ room, onClose }: { room: MockRoom; onClose: () => void }) {
  const agents = room.agentIds.map(agentById)
  const me = useSession()?.user
  return (
    <aside className={styles.panel}>
      <header>
        <strong>Người tham gia <small>{agents.length + 1}</small></strong>
        <button aria-label="Thêm" ><Plus size={15} /></button>
        <button aria-label="Đóng" onClick={onClose}><X size={15} /></button>
      </header>
      <h3>Nhân viên (1)</h3>
      <div className={styles.row}>
        <span className={styles.avatar} style={{ background: currentUser.color }}>
          {me ? initials(me.name) : currentUser.initials}<i className={styles.on} />
        </span>
        <div>
          <strong>{me?.name ?? currentUser.name} <Crown size={12} color="var(--warning)" /></strong>
          <code>{me?.email ?? currentUser.handle}</code>
        </div>
      </div>
      {agents.length > 0 && <h3>Agents ({agents.length})</h3>}
      {agents.map((a) => (
        <div key={a.id} className={styles.row}>
          <span className={styles.avatar} style={{ background: a.color }}>{a.name.charAt(0)}<i className={styles.on} /></span>
          <div><strong>{a.name}</strong><code>{a.id}</code></div>
        </div>
      ))}
    </aside>
  )
}
