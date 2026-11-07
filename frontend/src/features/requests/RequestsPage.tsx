import { useEffect, useRef } from 'react'
import { BrandLogo, BrandMark } from '../../shell/BrandMark'
import { useStore } from '../../shell/store'
import { Composer } from '../rooms/Composer'
import { pendingItem, type ThreadItem } from '../../mocks/staff'
import { ParallelRail, stillTyping, ThreadItemView, useTypedVersion, workingGroup } from './ThreadItems'
import styles from './RequestsPage.module.css'

// Ví dụ cho room mới, theo các việc thường gặp ở quầy.
const examples = [
  'Kiểm tra tồn kho iPhone 15 128GB ở Quận 1',
  'Khách muốn trả máy vì lỗi màn hình, xem có được hoàn tiền không',
  'Soạn email xin lỗi khách vì giao hàng trễ 3 ngày',
]

// Một room của nhân viên; lịch sử room và "Room mới" nằm trong sidebar.
export function RequestsPage() {
  const { requests, activeRequestId, setActiveRequestId, submitRequest, reply, decide, stopRequest } = useStore()
  const active = requests.find((r) => r.id === activeRequestId)

  // `/rooms?session=<id>` (nút "Mở trên web" của bot Slack) mở thẳng room đó khi danh sách đã tải.
  // Mở xong thì bỏ tham số khỏi URL để chọn room khác không bị kéo về. Room không có trong danh sách
  // (của người khác, đã xoá) thì không mở gì.
  const linked = useRef<string | null>(null)
  useEffect(() => {
    linked.current = new URLSearchParams(window.location.search).get('session')
  }, [])
  useEffect(() => {
    const id = linked.current
    if (!id || !requests.some((r) => r.id === id)) return
    linked.current = null
    setActiveRequestId(id)
    window.history.replaceState(null, '', window.location.pathname)
  }, [requests, setActiveRequestId])
  // Hiện lần lượt: tin của agent còn đang gõ thì các tin tới sau chờ nó gõ xong
  useTypedVersion()
  const shown: ThreadItem[] = []
  for (const i of active?.items ?? []) {
    shown.push(i)
    if (stillTyping(i)) break
  }

  // Bám đáy như Claude Code: đang ở cuối thì luồng dài ra tới đâu (tin mới, chữ đang gõ, trace thêm dòng)
  // cuộn êm theo tới đó; tự cuộn lên đọc thì để yên. Đổi room thì xuống cuối ngay.
  const scrollRef = useRef<HTMLDivElement>(null)
  const columnRef = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const hasThread = !!active
  useEffect(() => {
    pinned.current = true
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activeRequestId])
  useEffect(() => {
    const el = scrollRef.current
    const column = columnRef.current
    if (!el || !column || typeof ResizeObserver === 'undefined') return
    const follow = new ResizeObserver(() => {
      if (pinned.current) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
    follow.observe(column)
    return () => follow.disconnect()
  }, [hasThread])
  // Chỉ thao tác của người dùng mới đổi chế độ bám, không phải lúc chính trang đang cuộn êm theo
  const userScrolled = () => requestAnimationFrame(() => {
    const el = scrollRef.current
    if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  })

  if (!active) {
    return (
      <div className={styles.fresh}>
        <div className={styles.freshInner}>
          <BrandMark size={48} />
          {/* Logo chữ BOA thay cho chữ "BOA"; trình đọc màn hình vẫn đọc "BOA" nhờ aria-label của logo */}
          <h1>Bạn cần <span className={styles.inlineLogo}><BrandLogo height={28} /></span> làm gì?</h1>
          <p>Mô tả việc cần làm như khi nhờ đồng nghiệp. <span className={styles.boaName}>BOA</span> sẽ tự chọn agent phù hợp và hỏi lại nếu thiếu thông tin.</p>
          <div className={styles.slot}>
            <Composer mentions={false} placeholder="Mô tả việc cần làm…" onSend={submitRequest} />
          </div>
          <div className={styles.examples}>
            {examples.map((e) => <button key={e} onClick={() => submitRequest(e)}>{e}</button>)}
          </div>
        </div>
      </div>
    )
  }

  const pending = pendingItem(active)
  const working = workingGroup(shown)
  // Room vừa gửi còn id tạm (máy chủ chưa tạo xong) thì chưa dừng được: nút dừng hiện nhưng khóa
  const stoppable = active.status === 'running' && !active.id.startsWith('tmp')
  // Khóa của bong bóng yêu cầu theo thứ tự trong room, không theo id: id tạm (room vừa tạo, yêu cầu vừa
  // gửi) thành id của máy chủ mà bong bóng không vẽ lại
  let nth = 0
  const keyOf = (i: ThreadItem) => (i.kind === 'request' ? `request-${nth++}` : i.id)
  return (
    <section className={styles.thread}>
      <header className={styles.head}>
        <h2>{active.title}</h2>
      </header>
      <div
        ref={scrollRef}
        className={styles.scroll}
        onWheel={userScrolled}
        onTouchMove={userScrolled}
        onKeyUp={userScrolled}
        onPointerUp={userScrolled}
      >
        {working && <ParallelRail item={working} />}
        <div ref={columnRef} className={styles.column}>
          {shown.map((i) => (
            <ThreadItemView
              key={keyOf(i)}
              item={i}
              onDecide={(itemId, value) => decide(active.id, itemId, value)}
              onAnswer={(body) => reply(active.id, body)}
            />
          ))}
        </div>
      </div>
      <div className={styles.composer}>
        <Composer
          mentions={false}
          placeholder={pending?.kind === 'clarify' ? 'Trả lời câu hỏi…' : 'Nhắn thêm trong room này…'}
          onSend={(body) => reply(active.id, body)}
          running={active.status === 'running'}
          onStop={stoppable ? () => stopRequest(active.id) : undefined}
        />
      </div>
    </section>
  )
}
