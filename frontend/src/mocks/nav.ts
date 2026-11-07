// Mock: cấu trúc điều hướng sidebar (ánh xạ từ band-to-phone-retail-mapping.md §1).
export type NavId = 'home' | 'agents' | 'teams' | 'rooms' | 'analytics' | 'sonar' | 'contacts' | 'requests' | 'skills'

export interface NavEntry {
  id: NavId
  label: string
  path: string
}

export const primaryNav: NavEntry[] = [
  { id: 'home', label: 'Trang chủ', path: '/home' },
  { id: 'agents', label: 'Agents', path: '/agents' },
  { id: 'rooms', label: 'Phiên làm việc', path: '/sessions' },
  { id: 'analytics', label: 'Báo cáo', path: '/analytics' },
]

// Nhân viên phòng ban chỉ gửi yêu cầu, duyệt và xem agent riêng (REQUIREMENTS §4.2, §5.2).
export const staffNav: NavEntry[] = [
  { id: 'requests', label: 'Room', path: '/rooms' },
  { id: 'skills', label: 'Agent của tôi', path: '/skills' },
]

// TODO(NOT VERIFIED): nhu cầu Sonar/Contacts trong bán lẻ chưa được Owner chốt; giữ để bám bố cục.
export const networkNav: NavEntry[] = [
  { id: 'sonar', label: 'Sonar', path: '/sonar' },
  { id: 'contacts', label: 'Danh bạ', path: '/contacts' },
]
