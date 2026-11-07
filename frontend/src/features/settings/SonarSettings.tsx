import { useState } from 'react'
import { SettingsRow, SettingsSection } from './SettingsSection'
import { Switch } from './Switch'
import styles from './SonarSettings.module.css'

// TODO: lưu cài đặt thật; hiện chỉ giữ trạng thái trong phiên.
export function SonarSettings() {
  const [discoverable, setDiscoverable] = useState(true)
  const [roomNames, setRoomNames] = useState(true)
  const [usage, setUsage] = useState(true)

  return (
    <SettingsSection title="Sonar">
      <h2 className={styles.heading}>Khám phá trong mạng LAN</h2>
      <SettingsRow
        title="Cho phép tìm thấy"
        description="Thông báo các agent của máy này tới người dùng Phone Retail khác trong mạng nội bộ (trang Sonar). Chỉ chia sẻ danh tính công khai, tín hiệu hoạt động sơ lược và số lượng tác vụ — không bao giờ gửi tên tác vụ, prompt hay dữ liệu đầu vào của công cụ. Tắt nghĩa là không mở cổng nào ra mạng."
        action={<Switch checked={discoverable} onChange={setDiscoverable} label="Cho phép tìm thấy" />}
      />
      <SettingsRow
        title="Chia sẻ tên phiên làm việc"
        description="Đồng thời công bố tiêu đề các phiên mà agent của bạn đang làm việc, để người khác thấy phiên theo tên thay vì chỉ thấy danh sách thành viên. Mặc định bật; tắt để chỉ hiện phiên theo thành viên. Chỉ có hiệu lực khi đang bật Cho phép tìm thấy."
        action={<Switch checked={roomNames} onChange={setRoomNames} label="Chia sẻ tên phiên làm việc" />}
      />
      <SettingsRow
        title="Chia sẻ ước tính chi phí"
        description="Đồng thời công bố ước tính quy đổi USD theo từng agent và từng phiên, tính theo bảng giá niêm yết. Đây không phải hoá đơn của nhà cung cấp hay phí đăng ký. Mặc định bật; tắt để giữ riêng ước tính. Chỉ có hiệu lực khi đang bật Cho phép tìm thấy."
        action={<Switch checked={usage} onChange={setUsage} label="Chia sẻ ước tính chi phí" />}
      />
    </SettingsSection>
  )
}
