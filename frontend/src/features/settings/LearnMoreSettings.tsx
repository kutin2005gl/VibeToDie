import { ExternalLink } from '../../components/icons'
import { SettingsSection } from './SettingsSection'
import styles from './LearnMoreSettings.module.css'

// TODO: chưa có URL thật; nối vào tài liệu/README khi đã triển khai.
const links = [
  { title: 'Phone Retail là gì?', description: 'Cách Phone Retail phối hợp các agent hỗ trợ nhân viên chăm sóc khách hàng.' },
  { title: 'Tài liệu Phone Retail', description: 'Hướng dẫn và tham chiếu khi dùng Phone Retail.' },
  { title: 'Cài đặt Phone Retail Desktop', description: 'Cài ứng dụng desktop trên máy của bạn.' },
]

export function LearnMoreSettings() {
  return (
    <SettingsSection title="Tìm hiểu thêm">
      <div className={styles.list}>
        {links.map((l) => (
          <button key={l.title} className={styles.card}>
            <span>
              <span className={styles.title}>{l.title}</span>
              <span className={styles.desc}>{l.description}</span>
            </span>
            <ExternalLink size={16} />
          </button>
        ))}
      </div>
    </SettingsSection>
  )
}
