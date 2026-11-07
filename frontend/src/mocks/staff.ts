// Mock: màn nhân viên phòng ban. Toàn bộ là dữ liệu giả theo kịch bản demo trong REQUIREMENTS §4.2.
// TODO: thay bằng API task/room khi backend có endpoint.

import type { ReactNode } from 'react'

export type RequestStatus = 'waiting' | 'running' | 'done' | 'failed'

export interface TraceStep {
  agent: string
  action: string
  status: 'ok' | 'retry' | 'fail'
  note?: string
}

export type Decision = { value: 'yes' | 'no'; time: string }

export type ThreadItem =
  | { kind: 'request'; id: string; time: string; body: string }
  | { kind: 'route'; id: string; time: string; body: string }
  | { kind: 'result'; id: string; time: string; agent: string; title: string; body: string[]; trace: TraceStep[]; tries?: number }
  | {
      kind: 'approval'; id: string; time: string; title: string; facts: [string, string][]
      email: { to: string; subject: string; body: string }; decision?: Decision
      // Sau khi duyệt: hệ thống đã chạy hành động chưa
      sent?: 'sending' | 'done' | 'failed'
    }
  | { kind: 'clarify'; id: string; time: string; question: string; options: string[]; answer?: string }
  | { kind: 'skill'; id: string; time: string; name: string; summary: string; checks: string[]; tools: string[]; decision?: Decision }
  // `stopped`: nhân viên tự dừng lượt chạy, không phải lỗi
  | { kind: 'failed'; id: string; time: string; body: string; trace: TraceStep[]; stopped?: boolean }
  | { kind: 'reply'; id: string; time: string; body: string }
  // Tin của một agent trong chuỗi giao việc; `agent`, `to` và `mentions[].agent` là tên mandate.
  // `mentions`: Điều phối giao từng phần cho agent nào. `status`: agent đang làm (`since`, đồng hồ
  // chạy, chưa có nội dung) hoặc đã làm xong trong `seconds` giây. `at`: lúc máy chủ có tin (ISO),
  // để chỉ tin vừa tới mới hiện từng chữ. `work`: chỉ màn quản trị, những gì agent đã làm để ra tin
  // này (gọi model, công cụ, lỗi), hiện ngay dưới tên.
  | {
      kind: 'message'; id: string; time: string; at?: string; agent: string; to?: string; body: string[]
      mentions?: { agent: string; text: string }[]; drafts?: { title: string; body: string }[]
      details?: string[]; status?: MessageStatus; work?: ReactNode
    }
  // Các step Điều phối giao chạy cùng lúc, mỗi phần tử một agent với việc và trạng thái của nó
  | { kind: 'parallel'; id: string; time: string; members: ParallelMember[] }

export type MessageStatus = { label: 'Thinking' | 'Reviewing' | 'Working' | 'Worked'; since?: string; seconds?: number }

// `working`: đang làm (`since`, đồng hồ chạy); `done`: đã trả lời trong `seconds` giây; `failed`: không xong
export type ParallelMember = {
  id: string; agent: string; label: string; state: 'working' | 'done' | 'failed'; since: string; seconds?: number
}

export interface StaffRequest {
  id: string
  title: string
  status: RequestStatus
  updated: string
  items: ThreadItem[]
}

/** Item đang chờ nhân viên (duyệt, trả lời, duyệt skill); không có thì yêu cầu không ở trạng thái chờ. */
export function pendingItem(r: StaffRequest) {
  return r.items.find(
    (i) => (i.kind === 'approval' || i.kind === 'skill') ? !i.decision : i.kind === 'clarify' ? !i.answer : false,
  )
}

export function statusText(r: StaffRequest) {
  const p = pendingItem(r)
  if (p) return p.kind === 'clarify' ? 'Cần bạn trả lời' : 'Chờ bạn duyệt'
  return { waiting: 'Chờ bạn', running: 'Đang xử lý', done: 'Xong', failed: 'Không hoàn thành' }[r.status]
}

export const staffRequests: StaffRequest[] = [
  {
    id: 'q1',
    title: 'Khiếu nại iPhone 15 lỗi loa sau 10 ngày',
    status: 'waiting',
    updated: '10:12',
    items: [
      {
        kind: 'request', id: 'q1-1', time: '10:08',
        body: 'Khách Trần Thị Mai (đơn DH-10231) mua iPhone 15 128GB ngày 18/10, loa ngoài rè từ hôm qua. Khách muốn trả máy hoàn tiền. Kiểm tra giúp có đủ điều kiện không.',
      },
      { kind: 'route', id: 'q1-2', time: '10:08', body: 'Chuyển cho Chăm sóc khách · xử lý khiếu nại' },
      {
        kind: 'result', id: 'q1-3', time: '10:11', agent: 'Chăm sóc khách', title: 'Đủ điều kiện hoàn tiền',
        body: [
          'Đơn DH-10231 mua 18/10, còn trong 30 ngày đổi trả. Lỗi loa thuộc lỗi phần cứng của nhà sản xuất, không có dấu hiệu rơi vỡ hay vào nước theo phiếu tiếp nhận.',
          'Đề xuất hoàn 100% giá trị máy vì khách đã chọn hoàn tiền thay vì đổi máy.',
        ],
        tries: 2,
        trace: [
          { agent: 'Chăm sóc khách', action: 'get_order(DH-10231)', status: 'ok' },
          { agent: 'Chăm sóc khách', action: 'get_return_policy(apple, 30d)', status: 'ok' },
          { agent: 'Chăm sóc khách', action: 'Kiểm tra bằng code', status: 'retry', note: 'Lần 1 thiếu ngày mua trong lập luận; chạy lại' },
          { agent: 'Chăm sóc khách', action: 'Kiểm tra bằng code', status: 'ok' },
        ],
      },
      {
        kind: 'approval', id: 'q1-4', time: '10:12', title: 'Hoàn tiền cho khách?',
        facts: [
          ['Khách', 'Trần Thị Mai · 0903 •••• 218'],
          ['Đơn', 'DH-10231 · iPhone 15 128GB'],
          ['Số tiền', '19.990.000 ₫'],
          ['Lý do', 'Lỗi loa ngoài, trong hạn đổi trả 30 ngày'],
        ],
        email: {
          to: 'mai.tran@example.test',
          subject: 'Hư gì đổi nấy xác nhận hoàn tiền đơn DH-10231',
          body: 'Chào chị Mai, cửa hàng đã kiểm tra và đồng ý hoàn 19.990.000 ₫ cho đơn DH-10231. Chị vui lòng mang máy và hộp đến chi nhánh Quận 1 trong 7 ngày tới…',
        },
      },
    ],
  },
  {
    id: 'q2',
    title: 'Gửi lại hóa đơn cho khách Lê Văn Hùng',
    status: 'waiting',
    updated: '09:54',
    items: [
      { kind: 'request', id: 'q2-1', time: '09:52', body: 'Khách Lê Văn Hùng xin gửi lại hóa đơn điện tử qua email.' },
      { kind: 'route', id: 'q2-2', time: '09:52', body: 'Chuyển cho Chăm sóc khách · gửi chứng từ' },
      {
        kind: 'clarify', id: 'q2-3', time: '09:54',
        question: 'Khách Lê Văn Hùng có 2 đơn trong 3 tháng gần đây. Gửi hóa đơn của đơn nào?',
        options: ['DH-09877 · Galaxy A55 · 02/10', 'DH-10102 · Tai nghe Buds FE · 14/10', 'Cả hai đơn'],
      },
    ],
  },
  {
    id: 'q3',
    title: 'Tra bảo hành theo số IMEI',
    status: 'waiting',
    updated: 'Hôm qua',
    items: [
      { kind: 'request', id: 'q3-1', time: '16:20', body: 'Tra hạn bảo hành của máy IMEI 356789104455120.' },
      { kind: 'route', id: 'q3-2', time: '16:20', body: 'Chưa có agent nào làm việc này · tạo skill mới' },
      {
        kind: 'skill', id: 'q3-3', time: '16:23', name: 'Tra bảo hành theo IMEI',
        summary: 'Nhận số IMEI, tìm đơn bán tương ứng rồi tính ngày hết bảo hành theo chính sách của hãng.',
        checks: ['Đúng định dạng đầu vào/đầu ra', 'Chỉ đọc dữ liệu, không ghi', 'Chạy thử 3 IMEI mẫu: đúng 3/3'],
        tools: ['find_order_by_imei', 'get_warranty_policy'],
      },
    ],
  },
  {
    id: 'q4',
    title: 'Tồn kho Galaxy A55 ở chi nhánh Quận 1',
    status: 'done',
    updated: 'Hôm qua',
    items: [
      { kind: 'request', id: 'q4-1', time: '14:02', body: 'Galaxy A55 bản 256GB còn màu nào ở Quận 1?' },
      { kind: 'route', id: 'q4-2', time: '14:02', body: 'Chuyển cho Kho hàng · tra tồn kho' },
      {
        kind: 'result', id: 'q4-3', time: '14:03', agent: 'Kho hàng', title: 'Còn 2 màu',
        body: ['Quận 1 còn Xanh băng (4 máy) và Đen (1 máy). Màu Tím hết, dự kiến về 02/11.'],
        trace: [
          { agent: 'Kho hàng', action: 'check_stock(galaxy-a55, 256GB, q1)', status: 'ok' },
          { agent: 'Kho hàng', action: 'Kiểm tra bằng code', status: 'ok' },
        ],
      },
    ],
  },
  {
    id: 'q5',
    title: 'Tổng hợp đổi trả tuần 42',
    status: 'failed',
    updated: '21/10',
    items: [
      { kind: 'request', id: 'q5-1', time: '08:30', body: 'Tổng hợp các ca đổi trả tuần 42 theo chi nhánh.' },
      { kind: 'route', id: 'q5-2', time: '08:30', body: 'Chuyển cho Điều phối · cần nhiều bước' },
      {
        kind: 'failed', id: 'q5-3', time: '08:41',
        body: 'Không hoàn thành sau 5 lần thử: dữ liệu đổi trả của chi nhánh Thủ Đức tuần 42 chưa được nhập. Bổ sung dữ liệu rồi gửi lại yêu cầu.',
        trace: [
          { agent: 'Kho hàng', action: 'list_returns(week=42)', status: 'ok' },
          { agent: 'Điều phối', action: 'Kiểm tra bằng code', status: 'fail', note: 'Thiếu chi nhánh Thủ Đức' },
          { agent: 'Điều phối', action: 'Thử lại 4 lần', status: 'fail', note: 'Vẫn thiếu dữ liệu' },
        ],
      },
    ],
  },
]
