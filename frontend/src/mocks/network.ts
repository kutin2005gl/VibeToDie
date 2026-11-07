import { agents } from './agents'

// Mock: Sonar và Danh bạ. Cả hai chưa có dữ liệu (khớp trạng thái trống trong screenshot).
export interface MockContact {
  id: string
  identity: string
  connectedTo: string
}

export const directoryPeople: string[] = []
export const directoryTeams: string[] = []
export const contacts: MockContact[] = []

// Lựa chọn bộ lọc và danh tính gửi lời mời: "Bạn" cùng các agent của mình.
export const contactFilterOptions = [
  { value: 'all', label: 'Mọi người' },
  { value: 'you', label: 'Bạn' },
  ...agents.map((a) => ({ value: a.id, label: a.name })),
]
export const identityOptions = [
  { value: 'you', label: 'như Bạn' },
  ...agents.map((a) => ({ value: a.id, label: `như ${a.name}` })),
]
