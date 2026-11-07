import { useState } from 'react'
import { Select } from './Select'
import { SettingsRow, SettingsSection } from './SettingsSection'
import { Switch } from './Switch'
import styles from './NotificationSettings.module.css'

const taskUpdateOptions = ['Chỉ khi hoàn tất', 'Mọi thay đổi trạng thái', 'Không thông báo']

// TODO: lưu cài đặt thật (localStorage/API); hiện chỉ giữ trạng thái trong phiên.
export function NotificationSettings() {
  const [mentions, setMentions] = useState(true)
  const [requests, setRequests] = useState(true)
  const [taskUpdates, setTaskUpdates] = useState(taskUpdateOptions[0])

  return (
    <SettingsSection title="Thông báo">
      <div className={styles.intro}>
        <h2>Nhóm thông báo</h2>
        <p>Các cài đặt này áp dụng cho bản cài Phone Retail trên máy này.</p>
      </div>
      <SettingsRow
        title="Được nhắc trực tiếp"
        description="Thông báo khi có người nhắc trực tiếp đến bạn trong phiên làm việc."
        action={<Switch checked={mentions} onChange={setMentions} label="Được nhắc trực tiếp" />}
      />
      <SettingsRow
        title="Yêu cầu từ agent"
        description="Thông báo khi agent đặt câu hỏi hoặc xin quyền (ví dụ duyệt hoàn tiền)."
        action={<Switch checked={requests} onChange={setRequests} label="Yêu cầu từ agent" />}
      />
      <SettingsRow
        title="Cập nhật tác vụ"
        description="Chọn thay đổi trạng thái tác vụ nào sẽ gửi thông báo."
        action={<Select value={taskUpdates} options={taskUpdateOptions} onChange={setTaskUpdates} label="Cập nhật tác vụ" width={192} />}
      />
    </SettingsSection>
  )
}
