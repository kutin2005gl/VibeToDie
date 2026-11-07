import { Check, ChevronLeft, ExternalLink, MessageSquarePlus, Pencil, Trash2 } from '../../components/icons'
import { useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useStore } from '../../shell/store'
import { AvatarStack } from '../../components/Avatar'
import { Button } from '../../components/Button'
import { CopyButton } from '../../components/CopyButton'
import { PopupMenu, type MenuItem } from '../../components/PopupMenu'
import { agentCatalog } from '../../mocks/agentCatalog'
import { agentById } from '../../mocks/agents'
import { EditTeamDialog } from './EditTeamDialog'
import styles from './TeamDetailPage.module.css'

// TODO: "Xoá đội" chưa có hành vi thật (cần API và hộp xác nhận).
export function TeamDetailPage() {
  const { teamId } = useParams<{ teamId: string }>()
  const { teams, updateTeam, createRoom } = useStore()
  const navigate = useRouter().push
  const [editing, setEditing] = useState(false)
  const team = teams.find((t) => t.id === teamId)

  if (!team) {
    return (
      <div className={styles.missing}>
        <p>Không tìm thấy đội.</p>
        <Link href="/teams">Về danh sách đội</Link>
      </div>
    )
  }

  const members = team.agentIds.map((id) => agentCatalog.find((a) => a.id === id)).filter((a) => a !== undefined)
  const newRoom = () => {
    createRoom(team.name, team.agentIds)
    navigate('/sessions')
  }
  const icon = { size: 15, strokeWidth: 1.6 }
  const menu: MenuItem[] = [
    { label: 'Phiên mới', icon: <MessageSquarePlus {...icon} />, onSelect: newRoom },
    { label: 'Sửa đội', icon: <Pencil {...icon} />, onSelect: () => setEditing(true) },
    { label: 'Xoá đội', icon: <Trash2 {...icon} />, danger: true, separator: true, onSelect: () => undefined },
  ]

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link href="/teams" className={styles.back} aria-label="Quay lại danh sách đội"><ChevronLeft size={18} /></Link>
        <AvatarStack agents={team.agentIds.map(agentById)} max={3} size={22} />
        <div className={styles.titleBlock}>
          <h1>{team.name}</h1>
          <p>{team.description}</p>
        </div>
        <div className={styles.actions}>
          <Button onClick={() => setEditing(true)}>Sửa đội</Button>
          <Button variant="primary" onClick={newRoom}>Phiên mới</Button>
          <PopupMenu items={menu} />
        </div>
      </header>

      <div className={styles.content}>
        <div className={styles.column}>
          <h2>Thành viên · {members.length} / {team.agentIds.length} trong danh sách của bạn</h2>
          <ul className={styles.members}>
            {members.map((a) => (
              <li key={a.id}>
                <span className={styles.avatar} style={{ background: a.color }}>{a.name.charAt(0)}</span>
                <div className={styles.who}>
                  <strong>{a.name}</strong>
                  <span className={styles.handle}>
                    <code>{a.handle}</code><CopyButton value={a.handle} label="Sao chép handle" />
                    <span className={styles.chip}>{a.provider}</span>
                  </span>
                </div>
                <span className={styles.roster}><Check size={13} strokeWidth={2} />Trong danh sách</span>
                <Link href={`/agents/${a.id}`} className={styles.open} aria-label={`Mở agent ${a.name}`}><ExternalLink size={14} /></Link>
              </li>
            ))}
          </ul>

          <div className={styles.guideHead}>
            <h2>Hướng dẫn của đội</h2>
            <button onClick={() => setEditing(true)}>Sửa hướng dẫn</button>
          </div>
          <pre className={styles.guide}>{team.guidelines || 'Chưa có hướng dẫn.'}</pre>
        </div>
      </div>

      {editing && (
        <EditTeamDialog
          team={team}
          onCancel={() => setEditing(false)}
          onSave={(patch) => { updateTeam(team.id, patch); setEditing(false) }}
        />
      )}
    </div>
  )
}
