import { useState } from 'react'
import { ExternalLink, MessageSquarePlus, Pencil, Trash2, Users } from '../../components/icons'
import { useRouter } from 'next/navigation'
import { useStore } from '../../shell/store'
import { PageHeader } from '../../components/PageHeader'
import { Button } from '../../components/Button'
import { PopupMenu, type MenuItem } from '../../components/PopupMenu'
import { SearchBar } from '../../components/SearchBar'
import { AvatarStack } from '../../components/Avatar'
import { agentById } from '../../mocks/agents'
import { EditTeamDialog } from './EditTeamDialog'
import type { MockTeam } from '../../mocks/agentCatalog'
import styles from './TeamsPage.module.css'

// TODO(NOT VERIFIED): form tạo team (nút "Đội mới") chưa có screenshot.
// TODO: Xoá đội chưa có hành vi thật (cần API); xoá nên có hộp xác nhận.
export function TeamsPage() {
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<MockTeam | null>(null)
  const navigate = useRouter().push
  const { teams, updateTeam, createRoom } = useStore()
  const list = teams.filter((t) => !q || `${t.name} ${t.description}`.toLowerCase().includes(q.toLowerCase()))
  const icon = { size: 15, strokeWidth: 1.6 }
  const menuFor = (t: MockTeam): MenuItem[] => [
    { label: 'Mở đội', icon: <ExternalLink {...icon} />, onSelect: () => navigate(`/teams/${t.id}`) },
    { label: 'Phiên mới', icon: <MessageSquarePlus {...icon} />, onSelect: () => { createRoom(t.name, t.agentIds); navigate('/sessions') } },
    { label: 'Sửa đội', icon: <Pencil {...icon} />, onSelect: () => setEditing(t) },
    { label: 'Xoá đội', icon: <Trash2 {...icon} />, danger: true, separator: true, onSelect: () => undefined },
  ]

  return (
    <>
      <PageHeader
        title="Đội agent"
        actions={
          <>
            <Button>Thư viện</Button>
            <Button variant="primary"><Users size={14} /> Đội mới</Button>
          </>
        }
      />
      <div className={styles.body}>
        <SearchBar value={q} onChange={setQ} placeholder="Tìm đội…" />
        <div className={styles.grid}>
          {list.map((t) => (
            <article
              key={t.id}
              className={styles.card}
              tabIndex={0}
              role="link"
              aria-label={`Mở đội ${t.name}`}
              onClick={() => navigate(`/teams/${t.id}`)}
              onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) navigate(`/teams/${t.id}`) }}
            >
              <header>
                <strong>{t.name}</strong>
                <AvatarStack agents={t.agentIds.map(agentById)} max={3} />
                <PopupMenu items={menuFor(t)} />
              </header>
              <p>{t.description}</p>
              <small>{t.agentIds.map((id) => agentById(id).name).join(' · ')}</small>
              <small className={styles.roster}>{t.agentIds.length} / {t.agentIds.length} agent trong danh sách của bạn</small>
            </article>
          ))}
        </div>
        {list.length === 0 && <p className={styles.empty}>Không có đội phù hợp.</p>}
      </div>
      {editing && (
        <EditTeamDialog
          team={editing}
          onCancel={() => setEditing(null)}
          onSave={(patch) => { updateTeam(editing.id, patch); setEditing(null) }}
        />
      )}
    </>
  )
}
