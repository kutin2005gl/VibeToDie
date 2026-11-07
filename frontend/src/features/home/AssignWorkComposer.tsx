import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Send } from '../../components/icons'
import { useStore } from '../../shell/store'
import styles from './AssignWorkComposer.module.css'

// Giao việc từ trang chủ: tạo room thật (như nhân viên) rồi mở /rooms để theo dõi các agent chạy.
// Không chọn agent hay nhà cung cấp: Jev tự định tuyến mọi yêu cầu.
export function AssignWorkComposer() {
  const [text, setText] = useState('')
  const { submitRequest } = useStore()
  const router = useRouter()

  function submit() {
    submitRequest(text.trim())
    setText('')
    router.push('/rooms')
  }

  return (
    <section>
      <h2 className={styles.title}>Nhập khiếu nại</h2>
      <div className={styles.box}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && text.trim()) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder="Mô tả khiếu nại của khách…"
          rows={2}
        />
        <div className={styles.row}>
          <span className={styles.hint}>Gửi xong sẽ mở room để theo dõi các agent xử lý</span>
          <button className={styles.send} disabled={!text.trim()} onClick={submit} aria-label="Gửi">
            <Send size={16} />
          </button>
        </div>
      </div>
    </section>
  )
}
