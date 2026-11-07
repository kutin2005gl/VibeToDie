import type { MockAgent } from './agents'

// Mock: danh mục agent cho màn Agents/Teams; id = tên mandate trong ai/app/mandates. Số liệu là dữ liệu giả.
export interface MockAgentDetail extends MockAgent {
  handle: string
  description: string
  provider: string
  runtime: string
  sessions: string
  rooms: number
  cost7d: string
  tag: string
  messages: number
  toolCalls: number
  errors: number
  online: boolean
}

export const agentCatalog: MockAgentDetail[] = [
  {
    id: 'coordinator', name: 'Điều phối', color: 'var(--series-2)', handle: 'phoneretail/coordinator',
    description: 'Lập kế hoạch cho yêu cầu nhiều bước, giao từng bước cho agent phòng ban, duyệt kết quả và tổng hợp câu trả lời.',
    provider: 'Claude Code', runtime: 'Headless', sessions: '1/4 phiên', rooms: 2, cost7d: '$1.20', tag: 'điều phối',
    messages: 412, toolCalls: 96, errors: 0, online: true,
  },
  {
    id: 'customer_service', name: 'Chăm sóc khách hàng', color: 'var(--series-1)', handle: 'phoneretail/customer_service',
    description: 'Tư vấn sản phẩm, khuyến mãi và chính sách cho khách; soạn nội dung gửi khách và tổng hợp phản hồi.',
    provider: 'Claude Code', runtime: 'Headless', sessions: '2/4 phiên', rooms: 2, cost7d: '$2.45', tag: 'CSKH',
    messages: 538, toolCalls: 121, errors: 1, online: true,
  },
  {
    id: 'orders', name: 'Đơn hàng', color: 'var(--series-3)', handle: 'phoneretail/orders',
    description: 'Tra cứu đơn hàng, tồn kho và thông tin máy; tính tiền hoàn, phí và giá trị đơn.',
    provider: 'Codex', runtime: 'Headless', sessions: '0/4 phiên', rooms: 1, cost7d: '$0.86', tag: 'đơn hàng',
    messages: 203, toolCalls: 187, errors: 0, online: true,
  },
  {
    id: 'knowledge', name: 'Tra cứu quy trình', color: 'var(--series-4)', handle: 'phoneretail/knowledge',
    description: 'Trả lời câu hỏi về quy trình, chính sách nội bộ theo tài liệu SOP, có trích dẫn điều khoản.',
    provider: 'Codex', runtime: 'Headless', sessions: '1/4 phiên', rooms: 1, cost7d: '$1.02', tag: 'quy trình',
    messages: 276, toolCalls: 144, errors: 0, online: true,
  },
  {
    id: 'executive', name: 'Điều hành', color: 'var(--series-6)', handle: 'phoneretail/executive',
    description: 'Báo cáo, phân tích số liệu kinh doanh theo kỳ, cửa hàng, kênh; tóm tắt vấn đề và phương án cho Giám đốc.',
    provider: 'Claude Code', runtime: 'Headless', sessions: '0/4 phiên', rooms: 1, cost7d: '$0.92', tag: 'điều hành',
    messages: 97, toolCalls: 58, errors: 0, online: true,
  },
  {
    id: 'it_support', name: 'Hỗ trợ IT', color: 'var(--series-5)', handle: 'phoneretail/it_support',
    description: 'Xử lý sự cố phần mềm bán hàng, máy tính, máy in, mạng cửa hàng; tài khoản, phân quyền và ticket IT.',
    provider: 'Claude Code', runtime: 'Headless', sessions: '1/4 phiên', rooms: 1, cost7d: '$0.74', tag: 'IT',
    messages: 158, toolCalls: 63, errors: 0, online: false,
  },
  {
    id: 'factory', name: 'Xưởng agent', color: 'var(--series-7)', handle: 'phoneretail/factory',
    description: 'Soạn bản nháp agent phòng ban mới khi chưa có agent nào làm được phần việc được yêu cầu.',
    provider: 'Claude Code', runtime: 'Headless', sessions: '0/4 phiên', rooms: 0, cost7d: '$0.31', tag: 'tạo agent',
    messages: 24, toolCalls: 9, errors: 0, online: false,
  },
]

export interface MockTeam {
  id: string
  name: string
  description: string
  guidelines: string
  agentIds: string[]
}

export const teams: MockTeam[] = [
  {
    id: 't1',
    name: 'Quầy tư vấn điện thoại',
    description: 'Nhóm agent phối hợp tư vấn, kiểm kho, báo giá và chăm sóc sau bán cho khách tại cửa hàng.',
    guidelines: `# ĐỘI AGENT QUẦY TƯ VẤN PHONE RETAIL

MỤC TIÊU
Hỗ trợ nhân viên chăm sóc khách hàng xử lý yêu cầu của khách nhanh và chính xác. Chỉ báo cáo kết quả đã kiểm chứng, không giả lập tiến độ.

VAI TRÒ TRONG ĐỘI
- Điều phối: lập kế hoạch, giao việc, duyệt kết quả và tổng hợp câu trả lời.
- Chăm sóc khách hàng: tư vấn sản phẩm, khuyến mãi, chính sách và soạn nội dung gửi khách.
- Đơn hàng: tra đơn, tồn kho, thông tin máy và tính tiền.
- Tra cứu quy trình: trả lời theo tài liệu SOP, có trích dẫn.

QUY TRÌNH
1. Điều phối nhận yêu cầu, xác định agent phụ trách và tiêu chí hoàn thành.
2. Agent được giao tra cứu dữ liệu thật và báo lại kết quả kèm nguồn.
3. Điều phối kiểm tra kết quả trước khi giao bước sau.
4. Mọi thao tác hoàn tiền hoặc gửi email chỉ thực hiện sau khi nhân viên bấm Có.

PHỐI HỢP
- Giao tiếp bằng tiếng Việt; giữ nguyên các mã định danh kỹ thuật.
- Dùng @ để giao việc và bàn giao cho đúng agent.
- Không làm việc ngoài phạm vi được giao nếu chưa trao đổi với Điều phối.
`,
    agentIds: ['coordinator', 'customer_service', 'orders', 'knowledge'],
  },
]
