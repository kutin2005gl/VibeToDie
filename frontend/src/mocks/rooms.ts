// Mock: phiên làm việc (room). Toàn bộ nội dung là dữ liệu giả.
export interface MockUser {
  id: string
  name: string
  handle: string
  initials: string
  color: string
}

export const currentUser: MockUser = {
  id: 'u1', name: 'Nhân viên quầy', handle: 'staff-01', initials: 'NV', color: 'var(--series-8)',
}

// TODO(NOT VERIFIED): Band hiển thị các loại tin này thế nào chưa có screenshot.
// Các kind dưới đây chỉ suy ra từ legend Analytics (text, tool_call, tool_result, thought).
export type MessageKind = 'text' | 'thought' | 'tool_call' | 'tool_result'

export interface MockMessage {
  id: string
  authorId: string // 'u1' hoặc id agent
  kind: MessageKind
  body: string
  time: string
  mentions?: string[] // id agent được @
}

export interface MockRoom {
  id: string
  title: string
  agentIds: string[]
  updated: string
  messages: MockMessage[]
}

export const rooms: MockRoom[] = [
  {
    id: 'r1',
    title: 'Khách hỏi iPhone cho sinh viên',
    agentIds: ['router', 'advisor', 'inventory', 'pricing'],
    updated: '2 phút trước',
    messages: [
      { id: 'm1', authorId: 'u1', kind: 'text', time: '10:02', mentions: ['advisor'], body: '@Tư vấn máy khách sinh viên, ngân sách khoảng 15 triệu, cần pin trâu và camera ổn.' },
      { id: 'm2', authorId: 'router', kind: 'text', time: '10:02', body: 'Đã chuyển yêu cầu cho Tư vấn máy.' },
      { id: 'm3', authorId: 'advisor', kind: 'thought', time: '10:03', body: 'Ngân sách 15 triệu: cân nhắc 3 dòng phổ thông, ưu tiên pin và camera.' },
      { id: 'm4', authorId: 'advisor', kind: 'text', time: '10:03', mentions: ['inventory'], body: '@Kho hàng còn 3 mẫu này không, bản 128GB?' },
      { id: 'm5', authorId: 'inventory', kind: 'tool_call', time: '10:03', body: 'check_stock(models=3, storage=128GB)' },
      { id: 'm6', authorId: 'inventory', kind: 'tool_result', time: '10:04', body: 'Còn hàng 2/3 mẫu tại Quận 1; mẫu thứ 3 hết.' },
      { id: 'm7', authorId: 'pricing', kind: 'text', time: '10:05', body: 'Có ưu đãi trả góp 0% 6 tháng cho cả 2 mẫu còn hàng.' },
    ],
  },
  {
    id: 'r2',
    title: 'Phiên mới',
    agentIds: [],
    updated: 'vừa xong',
    messages: [],
  },
]
