import { useState } from 'react'
import { AtSign, Paperclip, Pause, Send } from '../../components/icons'
import styles from './Composer.module.css'

// TODO(NOT VERIFIED): popup mention, phím tắt gửi, file đính kèm. Hiện `@` chỉ chèn ký tự, Enter gửi, Shift+Enter xuống dòng.
interface Props {
  onSend: (body: string) => void
  placeholder?: string
  /** Nhân viên không gắn thẻ agent (Jev tự chọn), nên màn nhân viên tắt nút @. */
  mentions?: boolean
  /** Room đang chạy: nút gửi thành nút dừng, để nhân viên thấy việc vẫn đang làm và dừng được. */
  running?: boolean
  onStop?: () => void
}

export function Composer({
  onSend, placeholder = 'Gắn thẻ agent và mô tả việc cần làm…', mentions = true, running = false, onStop,
}: Props) {
  const [text, setText] = useState('')
  const submit = () => {
    const body = text.trim()
    if (!body || running) return
    onSend(body)
    setText('')
  }
  return (
    <div className={styles.wrap}>
      <div className={styles.box}>
        <textarea
          value={text}
          rows={1}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <div className={styles.row}>
          {mentions && <button aria-label="Gắn thẻ agent" onClick={() => setText((t) => t + '@')}><AtSign size={16} /></button>}
          <button aria-label="Đính kèm"><Paperclip size={16} /></button>
          {running ? (
            <button className={`${styles.send} ${styles.stop}`} aria-label="Dừng lượt chạy" title="Dừng lượt chạy"
              disabled={!onStop} onClick={onStop}>
              <Pause size={16} />
            </button>
          ) : (
            <button className={styles.send} aria-label="Gửi" disabled={!text.trim()} onClick={submit}><Send size={16} /></button>
          )}
        </div>
      </div>
    </div>
  )
}
