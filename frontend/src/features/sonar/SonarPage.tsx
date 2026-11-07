import { useState } from 'react'
import { Mail, Radar, Users } from '../../components/icons'
import { PageHeader } from '../../components/PageHeader'
import { SearchBar } from '../../components/SearchBar'
import { Toggle } from '../../components/Toggle'
import { EmptyState } from '../../components/EmptyState'
import { Button } from '../../components/Button'
import { directoryPeople, directoryTeams } from '../../mocks/network'
import styles from './SonarPage.module.css'

type Tab = 'people' | 'teams'

// TODO(NOT VERIFIED): nhu cầu Sonar trong bán lẻ chưa được Owner chốt (xem band-to-phone-retail-mapping.md §6).
// TODO: "Mời qua email", "Mở Gmail", "Sao chép lời mời" chưa có hành vi; kết quả (mailto/clipboard/toast) chưa kiểm chứng.
export function SonarPage() {
  const [tab, setTab] = useState<Tab>('people')
  const [q, setQ] = useState('')
  const [discoverable, setDiscoverable] = useState(true)
  const noop = (e: React.MouseEvent) => e.preventDefault()

  return (
    <>
      <PageHeader title="Sonar" actions={<Toggle label="Cho phép tìm thấy" checked={discoverable} onChange={setDiscoverable} />} />
      <div className={styles.body}>
        <div className={styles.tabs} role="tablist">
          <button role="tab" aria-selected={tab === 'people'} className={tab === 'people' ? styles.on : ''} onClick={() => setTab('people')}>
            Người <b>{directoryPeople.length}</b>
          </button>
          <button role="tab" aria-selected={tab === 'teams'} className={tab === 'teams' ? styles.on : ''} onClick={() => setTab('teams')}>
            Đội <b>{directoryTeams.length}</b>
          </button>
        </div>
        <SearchBar value={q} onChange={setQ} placeholder="Tìm trong danh bạ…" />
        <div className={styles.empty}>
          {tab === 'people' ? (
            <EmptyState icon={<Radar size={32} />} title="Chưa có ai ở gần">
              <p>Chưa có ai khác có thể được tìm thấy trên mạng này.</p>
              <p className={styles.gap}>Không thấy bạn bè? Hãy gửi lời mời.</p>
              <Button variant="primary"><Mail size={14} /> Mời qua email</Button>
              <p>
                Không có ứng dụng mail? <a href="#gmail" onClick={noop}>Mở Gmail</a> · <a href="#copy" onClick={noop}>Sao chép nội dung lời mời</a>
              </p>
            </EmptyState>
          ) : (
            <EmptyState icon={<Users size={32} />} title="Chưa thấy đội nào">
              <p className={styles.narrow}>Các agent được tìm thấy chưa chia sẻ phiên nào, hoặc phiên của họ không có thành viên nào khác nhìn thấy được.</p>
            </EmptyState>
          )}
        </div>
      </div>
    </>
  )
}
