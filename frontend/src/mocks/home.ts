// Mock: dữ liệu trang chủ.
export interface MockSession {
  id: string
  title: string
  summary: string
  agentIds: string[]
  doneTasks: number
  totalTasks: number
  activity: number[] // sparkline, giá trị 0..1
}

export const sessions: MockSession[] = [
  {
    id: 's1',
    title: 'Khách hỏi iPhone cho sinh viên',
    summary:
      'Khách có ngân sách khoảng 15 triệu, cần máy pin tốt và camera ổn. Agent Tư vấn máy đã đề xuất 3 mẫu, đang chờ Kho hàng xác nhận tồn kho và Giá & khuyến mãi báo ưu đãi trả góp.',
    agentIds: ['advisor', 'inventory', 'pricing', 'router'],
    doneTasks: 3,
    totalTasks: 5,
    activity: [0, 0.1, 0, 0.3, 0.2, 0, 0.9, 0.2, 0.1, 0.1, 0.1],
  },
  {
    id: 's2',
    title: 'Yêu cầu bảo hành màn hình',
    summary: 'Khách mang máy mua cách đây 8 tháng, màn hình sọc ngang. Agent Chăm sóc khách đang tra cứu thời hạn bảo hành.',
    agentIds: ['care', 'router'],
    doneTasks: 1,
    totalTasks: 4,
    activity: [0, 0, 0.2, 0, 0, 0.4, 0, 0.1, 0, 0, 0.2],
  },
]

export interface MockOnboardingCard {
  id: string
  eyebrow: string
  title: string
  description: string
  action: string
  size: 'hero' | 'small'
  tone: 'green' | 'blue'
}

// TODO(NOT VERIFIED): ở Band các thẻ này có thể lật/kéo thả; chưa làm, chỉ hiển thị tĩnh.
export const onboardingCards: MockOnboardingCard[] = [
  { id: 'o1', eyebrow: 'AGENTS', title: 'Thêm agent cho quầy tư vấn', description: 'Gắn agent tư vấn, kho, giá và chăm sóc khách vào một phiên làm việc.', action: 'Tạo agent', size: 'hero', tone: 'green' },
  { id: 'o2', eyebrow: 'MẸO', title: 'Sắp xếp theo mức ưu tiên', description: 'Việc quan trọng nhất luôn nằm trên cùng.', action: 'Đã hiểu', size: 'hero', tone: 'green' },
  { id: 'o3', eyebrow: 'BẮT ĐẦU', title: 'Khám phá các thẻ', description: '0 / 7 đã xem', action: '', size: 'hero', tone: 'green' },
  { id: 'o4', eyebrow: 'TASKS', title: 'Mỗi việc một bảng', description: 'Theo dõi tra kho, báo giá, chốt đơn.', action: 'Xem cách dùng', size: 'small', tone: 'blue' },
  { id: 'o5', eyebrow: 'BÁO CÁO', title: 'Chi phí & hiệu suất', description: 'Theo dõi lượng tin nhắn và chi phí LLM.', action: 'Mở báo cáo', size: 'small', tone: 'blue' },
  { id: 'o6', eyebrow: 'KHÁCH', title: 'Danh bạ khách hàng', description: 'Lưu lịch sử mua và bảo hành.', action: 'Mở danh bạ', size: 'small', tone: 'blue' },
]

export const branches = ['Chi nhánh Quận 1', 'Chi nhánh Thủ Đức', 'Chi nhánh Cầu Giấy']
