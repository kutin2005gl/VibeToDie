import { FolderOpen, Sparkles, SquareTerminal, type IconComponent } from '../../components/icons'
import { useState } from 'react'
import { SettingsRow, SettingsSection } from './SettingsSection'
import { Switch } from './Switch'
import styles from './IntegrationsSettings.module.css'

interface Integration {
  id: 'claude-code' | 'codex'
  name: string
  description: string
  Icon: IconComponent
}

const integrations: Integration[] = [
  { id: 'claude-code', name: 'Claude Code', Icon: Sparkles, description: 'Kết nối phiên Claude Code với các phiên làm việc Phone Retail.' },
  { id: 'codex', name: 'Codex', Icon: SquareTerminal, description: 'Hiện Codex app-server khi tạo agent cục bộ. Phone Retail tự bật API thử nghiệm cần thiết.' },
]

// TODO: nút thư mục chưa mở được đường dẫn cài đặt; trạng thái bật/tắt chưa lưu.
export function IntegrationsSettings() {
  const [enabled, setEnabled] = useState<Record<Integration['id'], boolean>>({ 'claude-code': true, codex: true })

  return (
    <SettingsSection title="Tích hợp">
      <div className={styles.list}>
        {integrations.map(({ id, name, description, Icon }) => (
          <SettingsRow
            key={id}
            title={<span className={styles.name}><Icon size={15} />{name}</span>}
            description={description}
            action={
              <div className={styles.actions}>
                <button className={styles.folder} aria-label={`Mở thư mục ${name}`}><FolderOpen size={16} /></button>
                <Switch checked={enabled[id]} onChange={(v) => setEnabled((s) => ({ ...s, [id]: v }))} label={name} />
              </div>
            }
          />
        ))}
      </div>
    </SettingsSection>
  )
}
