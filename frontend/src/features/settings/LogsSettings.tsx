import { Copy, Download, FolderOpen, RefreshCw } from '../../components/icons'
import { useState } from 'react'
import { Select } from './Select'
import { SettingsSection } from './SettingsSection'
import styles from './LogsSettings.module.css'

const levelOptions = ['Info (mặc định)', 'Debug', 'Trace', 'Warn', 'Error']
const fileOptions = ['Dịch vụ nền (daemon)', 'Ứng dụng desktop', 'AI service']

// TODO: log giả; nối API đọc file log thật. Các nút chưa có hành vi.
const mockLog = [
  '2026-10-22T16:07:00.167Z  INFO api: POST /v1/tasks accepted task_id=t_8f21 provider="anthropic"',
  '2026-10-22T16:07:00.331Z  INFO worker: step started step=cskh_triage task_id=t_8f21',
  '2026-10-22T16:07:00.834Z  WARN ai: LLM response slow provider="anthropic" elapsed_ms=2791 outcome="success"',
  '2026-10-22T16:07:05.109Z  INFO worker: step finished step=cskh_triage task_id=t_8f21 outcome="success"',
  '2026-10-22T16:07:05.986Z  INFO worker: step started step=accounting_check task_id=t_8f21',
  '2026-10-22T16:07:06.782Z  WARN ai: LLM response slow provider="openai" elapsed_ms=5946 outcome="success"',
  '2026-10-22T16:07:07.642Z  INFO worker: awaiting human approval task_id=t_8f21 action="refund"',
].join('\n')

export function LogsSettings() {
  const [level, setLevel] = useState(levelOptions[0])
  const [file, setFile] = useState(fileOptions[0])

  return (
    <SettingsSection title="Nhật ký">
      <h2 className={styles.heading}>Gói hỗ trợ</h2>
      <p className={styles.desc}>
        Lưu nhật ký desktop, daemon và agent vào một tệp ZIP trên Desktop. Nhật ký có thể chứa hoạt động riêng tư; hãy xem lại tệp trước khi chia sẻ.
      </p>
      <button className={styles.bigBtn}><Download size={14} />Tạo gói hỗ trợ</button>

      <h2 className={`${styles.heading} ${styles.gap}`}>Ghi nhật ký</h2>
      <p className={styles.desc}>
        Điều chỉnh mức độ chi tiết daemon cục bộ ghi lại. Mức chi tiết hơn giúp chẩn đoán sự cố; có hiệu lực ở lần khởi động daemon tiếp theo.
      </p>
      <div className={styles.levelRow}>
        <div>
          <div className={styles.levelTitle}>Mức nhật ký daemon</div>
          <div className={styles.levelHint}>Mức cao ghi nhiều hơn. Debug và trace rất dài dòng.</div>
        </div>
        <Select value={level} options={levelOptions} onChange={setLevel} label="Mức nhật ký daemon" width={208} />
      </div>

      <h2 className={`${styles.heading} ${styles.gap}`}>Xem nhật ký</h2>
      <p className={styles.desc}>Các dòng gần nhất của tệp nhật ký đang chọn.</p>
      <div className={styles.toolbar}>
        <Select value={file} options={fileOptions} onChange={setFile} label="Tệp nhật ký" width={176} />
        <div className={styles.toolButtons}>
          <button className={styles.tool}><Copy size={14} />Sao chép nhật ký</button>
          <button className={styles.tool}><RefreshCw size={14} />Làm mới</button>
          <button className={styles.tool}><FolderOpen size={14} />Mở thư mục nhật ký</button>
        </div>
      </div>
      <pre className={styles.log} tabIndex={0}>{mockLog}</pre>
    </SettingsSection>
  )
}
