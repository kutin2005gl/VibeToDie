import { CheckCircle2 } from '../../components/icons'
import { useState, type ReactNode } from 'react'
import { Button } from '../../components/Button'
import { Select } from './Select'
import { SettingsSection } from './SettingsSection'
import styles from './RuntimeSettings.module.css'

const approvalOptions = ['Mặc định — chờ vô thời hạn', '5 phút', '30 phút', '2 giờ']
const feedOptions = ['Mặc định (agent của bạn và pull: đầy đủ · còn lại tóm tắt)', 'Đầy đủ', 'Tóm tắt', 'Tắt']
const onOptions = ['Mặc định (bật)', 'Bật', 'Tắt']

function Field({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div className={styles.field}>
      <label className={styles.label}>{label}</label>
      {children}
      <p className={styles.hint}>{hint}</p>
    </div>
  )
}

// TODO: "Lưu mặc định" chưa gọi API; giá trị chưa được lưu.
export function RuntimeSettings() {
  const [approval, setApproval] = useState(approvalOptions[0])
  const [feed, setFeed] = useState(feedOptions[0])
  const [ownerApprove, setOwnerApprove] = useState(onOptions[0])
  const [resume, setResume] = useState(onOptions[0])

  return (
    <SettingsSection title="Môi trường chạy">
      <div className={styles.card}>
        <CheckCircle2 size={16} className={styles.cardIcon} />
        <div>
          <div className={styles.cardTitle}>API thử nghiệm của Codex đã được bật</div>
          <p className={styles.cardDesc}>
            Phone Retail tự bật cho mọi kết nối Codex app-server do ứng dụng quản lý. Không cần đổi cấu hình Codex.
          </p>
        </div>
        <div className={styles.cardFoot}>Mọi phiên Codex đã biết đều có thể tiếp tục bằng công cụ phản hồi của Phone Retail.</div>
      </div>

      <h2 className={styles.heading}>Mặc định của agent</h2>
      <p className={styles.sub}>Mặc định cho agent mới. Để trống để dùng giá trị có sẵn. Cài đặt riêng của từng agent được ưu tiên hơn.</p>

      <Field label="Ngân sách nén (token đầu vào)" hint="Luồng hội thoại được nén chủ động khi đạt kích thước ngữ cảnh này. Có sẵn: 500k; 0 để tắt.">
        <input className={styles.input} placeholder="mặc định có sẵn" />
      </Field>
      <Field
        label="Thời gian chờ con người duyệt"
        hint="Phone Retail giữ yêu cầu cấp quyền mở đến khi có người quyết định. Các mức có giới hạn sẽ tự từ chối khi hết hạn. Thay đổi áp dụng cho yêu cầu mới; yêu cầu đang chờ giữ hạn hiển thị trên thẻ của nó."
      >
        <Select value={approval} options={approvalOptions} onChange={setApproval} label="Thời gian chờ duyệt" />
      </Field>
      <Field label="Hết hạn câu hỏi chung (giây)" hint="Để trống hoặc nhập 0 để chờ đến khi có người trả lời. Nhập số dương để huỷ câu hỏi chưa được trả lời.">
        <input className={styles.input} placeholder="mặc định có sẵn" />
      </Field>
      <Field label="Dừng agent nhàn rỗi sau (giây)" hint="Dừng agent nhàn rỗi sau khoảng này. Agent thức dậy khi có tin nhắn tiếp theo. Có sẵn: 600.">
        <input className={styles.input} placeholder="mặc định có sẵn" />
      </Field>
      <Field label="Nguồn cấp hoạt động của phiên" hint="Hiện các lệnh gọi công cụ và kết quả theo thời gian thực trong phiên của agent. Cài đặt riêng của agent được ưu tiên.">
        <Select value={feed} options={feedOptions} onChange={setFeed} label="Nguồn cấp hoạt động" width={320} />
      </Field>
      <Field
        label="Chủ phiên được duyệt yêu cầu cấp quyền"
        hint="Yêu cầu cấp quyền đang chờ hiện trong phiên của agent. Chủ phiên cùng tài khoản hoặc một người dùng có thể duyệt. Agent yêu cầu không được tự duyệt. Duyệt trong phiên chỉ áp dụng một lần."
      >
        <Select value={ownerApprove} options={onOptions} onChange={setOwnerApprove} label="Chủ phiên được duyệt" />
      </Field>
      <Field label="Tiếp tục luồng khi thức dậy" hint="Giữ ngữ cảnh hội thoại qua các chu kỳ nhàn rỗi/thức dậy.">
        <Select value={resume} options={onOptions} onChange={setResume} label="Tiếp tục luồng" />
      </Field>

      <Button variant="primary" className={styles.save}>Lưu mặc định</Button>
    </SettingsSection>
  )
}
