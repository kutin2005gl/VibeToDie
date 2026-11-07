import { CheckCircle2 } from '../../components/icons'
import { logout } from '../../api/auth'
import { Button } from '../../components/Button'
import { departmentLabel, initials, useSession } from '../../shell/session'
import { SettingsRow, SettingsSection } from './SettingsSection'
import { SlackLinkSettings } from './SlackLinkSettings'
import styles from './AccountSettings.module.css'

// TODO: "Xoá dữ liệu" chưa có hành vi (chưa có dữ liệu cục bộ nào ngoài phiên đăng nhập).
export function AccountSettings() {
  const session = useSession()
  if (!session) return null
  const { user } = session
  const departments = user.departments.map(departmentLabel).join(', ')
  // Đăng xuất làm session rỗng, RequireAuth tự đưa về màn đăng nhập.
  const signOut = () => void logout()
  return (
    <SettingsSection title="Tài khoản">
      <div className={styles.profile}>
        <span className={styles.avatar}>{initials(user.name)}</span>
        <div>
          <div className={styles.nameLine}>
            <span className={styles.name}>{user.name}</span>
            <span className={styles.badge}><CheckCircle2 size={12} />Đã đăng nhập</span>
          </div>
          <div className={styles.email}>{user.email}</div>
          <div className={styles.note}>
            {departments ? `Phòng ban: ${departments}` : 'Chưa được cấp phòng ban — liên hệ quản trị viên'}
          </div>
        </div>
      </div>
      <SlackLinkSettings key={user.id} />
      <SettingsRow
        title="Kết nối lại tài khoản"
        description="Đăng nhập lại để nhận phòng ban mới được cấp hoặc khi phiên không tự gia hạn được."
        action={<Button variant="primary" onClick={signOut}>Đăng nhập lại</Button>}
      />
      <SettingsRow
        title="Đăng xuất"
        description="Kết thúc phiên trên thiết bị này. Dữ liệu cục bộ vẫn được giữ."
        action={<Button className={styles.neutral} onClick={signOut}>Kết thúc phiên</Button>}
      />
      <SettingsRow
        title="Xoá dữ liệu cục bộ"
        description="Xoá các phiên làm việc, liên hệ và dữ liệu đệm của tài khoản này khỏi thiết bị."
        action={<Button className={styles.danger}>Xoá dữ liệu</Button>}
      />
    </SettingsSection>
  )
}
