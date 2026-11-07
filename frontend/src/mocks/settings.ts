// Mock: cấu trúc điều hướng trang Cài đặt và tài khoản đang đăng nhập.
export type SettingsSectionId =
  | 'account' | 'notifications' | 'general' | 'appearance' | 'sonar'
  | 'integrations' | 'runtime' | 'logs' | 'experiments' | 'learn-more'

export interface SettingsSection {
  id: SettingsSectionId
  label: string
}

export const settingsGroups: { label: string; items: SettingsSection[] }[] = [
  {
    label: 'Cá nhân',
    items: [
      { id: 'account', label: 'Tài khoản' },
      { id: 'notifications', label: 'Thông báo' },
    ],
  },
  {
    label: 'Ứng dụng',
    items: [
      { id: 'general', label: 'Chung' },
      { id: 'appearance', label: 'Giao diện' },
      { id: 'sonar', label: 'Sonar' },
    ],
  },
  {
    label: 'Agents',
    items: [
      { id: 'integrations', label: 'Tích hợp' },
      { id: 'runtime', label: 'Môi trường chạy' },
    ],
  },
  {
    label: 'Nâng cao',
    items: [
      { id: 'logs', label: 'Nhật ký' },
      { id: 'experiments', label: 'Thử nghiệm' },
      { id: 'learn-more', label: 'Tìm hiểu thêm' },
    ],
  },
]
