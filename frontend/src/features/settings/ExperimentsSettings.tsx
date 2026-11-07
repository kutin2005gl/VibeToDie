import { useState } from 'react'
import { SettingsRow, SettingsSection } from './SettingsSection'
import { Switch } from './Switch'
import styles from './ExperimentsSettings.module.css'

const experiments = [
  { id: 'agentDetails', title: 'Chi tiết agent nâng cao', description: 'Thêm Tổng quan và Hoạt động vào chi tiết agent. Các màn này hiện mức dùng, lỗi runtime và nhật ký hoạt động trực tiếp.' },
  { id: 'runtimeSetup', title: 'Thiết lập môi trường chạy', description: 'Hiện thẻ Thiết lập môi trường chạy trong chi tiết agent. Dùng để cấu hình, kiểm thử, sửa hoặc tắt mẫu runtime dùng lại. Việc tạo agent và các phiên đang chạy không đổi.' },
  { id: 'sandbox', title: 'Docker Sandbox', description: 'Hiện việc tạo, cấu hình và điều khiển Docker Sandbox trong ứng dụng desktop. Agent đã chạy trong sandbox vẫn giữ điều khiển khôi phục và dọn dẹp khi tắt thử nghiệm này. API của CLI và daemon không đổi.' },
  { id: 'inbox', title: 'Hộp thư', description: 'Thêm mục Hộp thư vào thanh bên desktop, gom các lần nhắc, câu hỏi và yêu cầu cấp quyền từ mọi phiên về một chỗ. Khi tắt, Trang chủ và bảng Công việc của từng phiên vẫn hiện câu hỏi và yêu cầu cấp quyền. Không đổi lệnh inbox của CLI.' },
  { id: 'sessions', title: 'Phiên làm việc', description: 'Thêm mục Phiên làm việc vào thanh bên desktop, liệt kê mọi tiến trình công cụ lập trình của agent cục bộ và phiên gắn với chúng trong một bảng. Khi tắt, tab Phiên của từng agent vẫn hiện các tiến trình của riêng agent đó. Không đổi lệnh sessions của CLI.' },
  { id: 'usage', title: 'Chẩn đoán mức dùng', description: 'Thêm mục Nâng cao bên dưới Mức dùng & Chi phí với chi tiết khôi phục và đối soát cục bộ. Báo cáo mức dùng và chi phí thông thường không đổi.' },
  { id: 'agentAdmin', title: 'Cho phép agent tạo/sửa agent', description: 'Cho phép các runtime agent được phát hiện tạo agent hoặc đổi hướng dẫn và mẫu runtime của agent. Việc đọc đã ẩn thông tin nhạy cảm vẫn dùng được khi tắt.' },
  { id: 'linear', title: 'Linear làm nguồn công việc', description: 'Hiện các issue Linear được giao trong cài đặt Kết nối, kèm xem trước và bắt đầu một chạm, đồng thời bật bộ thăm dò nền để tự bắt đầu (tuỳ chọn). Khi tắt, bộ thăm dò không chạy và không hiện giao diện Linear mới; kết nối Linear chỉ đọc hiện có không đổi.' },
]

// TODO: lưu trạng thái bật/tắt thật; hiện chỉ giữ trong phiên. Danh sách bám bản gốc, cân nhắc bỏ mục không dùng cho bán lẻ.
export function ExperimentsSettings() {
  const [on, setOn] = useState<Record<string, boolean>>({})

  return (
    <SettingsSection title="Thử nghiệm">
      <p className={styles.intro}>Các tính năng tuỳ chọn có thể bật. Mỗi mục đều tắt mặc định và có thể thay đổi hoặc bị gỡ ở bản sau.</p>
      {experiments.map((e) => (
        <SettingsRow
          key={e.id}
          title={e.title}
          description={e.description}
          action={<Switch checked={!!on[e.id]} onChange={(v) => setOn((s) => ({ ...s, [e.id]: v }))} label={e.title} />}
        />
      ))}
    </SettingsSection>
  )
}
