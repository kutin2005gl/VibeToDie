import { Download, RefreshCw, Trash2 } from '../../components/icons'
import { useState } from 'react'
import { SettingsRow, SettingsSection } from './SettingsSection'
import { Switch } from './Switch'
import styles from './GeneralSettings.module.css'

type Ring = 'Stable' | 'Beta' | 'Nightly'
const rings: Ring[] = ['Stable', 'Beta', 'Nightly']

// TODO: số phiên bản là dữ liệu giả; các nút (sửa/gỡ CLI, cập nhật) chưa có hành vi.
const mockVersions = { app: 'v0.1.0', daemon: 'v0.1.0', cli: 'v0.1.0', claudeCode: 'v0.1.0', available: 'v0.1.1' }

function SmallButton({ icon, children, primary }: { icon: React.ReactNode; children: React.ReactNode; primary?: boolean }) {
  return (
    <button className={`${styles.small} ${primary ? styles.primary : ''}`}>
      {icon}
      <span>{children}</span>
    </button>
  )
}

export function GeneralSettings() {
  const [ring, setRing] = useState<Ring>('Stable')
  const [background, setBackground] = useState(true)
  const [analytics, setAnalytics] = useState(true)

  return (
    <SettingsSection title="Chung">
      <div className={styles.group}>
        <h2 className={styles.heading}>Phiên bản &amp; CLI</h2>
        <SettingsRow title="Ứng dụng" action={<span className={styles.value}>{mockVersions.app}</span>} />
        <SettingsRow title="Dịch vụ nền (daemon)" action={<span className={styles.value}>{mockVersions.daemon}</span>} />
        <SettingsRow
          title="Công cụ dòng lệnh"
          description="Lệnh Phone Retail dùng chung với các tích hợp agent của ứng dụng."
          action={
            <div className={styles.stack}>
              <span className={styles.value}>{mockVersions.cli}</span>
              <div className={styles.buttons}>
                <SmallButton icon={<Download size={12} />}>sửa CLI</SmallButton>
                <SmallButton icon={<Trash2 size={12} />}>gỡ CLI</SmallButton>
              </div>
            </div>
          }
        />
        <SettingsRow
          title="Tích hợp Claude Code"
          description="Kết nối Claude Code với máy chủ Phone Retail qua ứng dụng desktop."
          action={<span className={styles.value}>{mockVersions.claudeCode}</span>}
        />
        <SettingsRow
          title="Thanh trạng thái Claude"
          description="Tuỳ chọn: hiện model, thư mục và mức dùng ngữ cảnh trong terminal."
          action={<SmallButton icon={<Download size={12} />}>cài thanh trạng thái</SmallButton>}
        />
        <SettingsRow
          title="Kênh cập nhật"
          description="Áp dụng cho lần kiểm tra tiếp theo trên máy này. Đổi kênh không bao giờ tự cài đặt."
          action={
            <div className={styles.segmented} role="group" aria-label="Kênh cập nhật">
              {rings.map((r) => (
                <button key={r} className={ring === r ? styles.segOn : ''} aria-pressed={ring === r} onClick={() => setRing(r)}>{r}</button>
              ))}
            </div>
          }
        />
        <SettingsRow
          title="Cập nhật ứng dụng"
          description={`Phone Retail ${mockVersions.available} đã có trên kênh ${ring.toLowerCase()}.`}
          action={
            <div className={styles.buttons}>
              <SmallButton primary icon={<Download size={12} />}>Cài bản cập nhật</SmallButton>
              <SmallButton icon={<RefreshCw size={12} />}>Kiểm tra cập nhật</SmallButton>
            </div>
          }
        />
        <SettingsRow
          title="Chạy nền"
          description="Giữ Phone Retail chạy khi đăng xuất và khởi động lại máy. Bật sẽ khởi động lại ứng dụng một lúc."
          action={<Switch checked={background} onChange={setBackground} label="Chạy nền" />}
        />
      </div>

      <div className={`${styles.group} ${styles.second}`}>
        <h2 className={styles.heading}>Phân tích sản phẩm</h2>
        <SettingsRow
          title="Chia sẻ dữ liệu sử dụng"
          description="Chia sẻ dữ liệu sử dụng với Phone Retail. Không bao gồm tin nhắn, prompt, tệp, đường dẫn, khoá và báo lỗi."
          action={<Switch checked={analytics} onChange={setAnalytics} label="Chia sẻ dữ liệu sử dụng" />}
        />
      </div>
    </SettingsSection>
  )
}
