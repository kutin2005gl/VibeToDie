import { agentById } from '../../mocks/agents'
import { currentUser, type MockMessage } from '../../mocks/rooms'
import { initials, useSession } from '../../shell/session'
import styles from './MessageCard.module.css'

const kindLabel: Record<MockMessage['kind'], string> = {
  text: '',
  thought: 'suy nghĩ',
  tool_call: 'gọi công cụ',
  tool_result: 'kết quả công cụ',
}

/*
 * TODO(NOT VERIFIED): bản TẠM. Screenshot Band chưa có room có tin nhắn nên chưa biết cách hiển thị
 * agent↔agent, tool_call/tool_result/thought, permission_request, mention, thu gọn/mở rộng.
 * Chỉ hiển thị: avatar, tên, giờ, nhãn loại tin, nội dung. Thiết kế lại sau khi có screenshot P0.
 */
export function MessageCard({ message }: { message: MockMessage }) {
  const me = useSession()?.user
  const isUser = message.authorId === currentUser.id
  const agent = isUser ? null : agentById(message.authorId)
  const name = isUser ? (me?.name ?? currentUser.name) : agent!.name
  const color = isUser ? currentUser.color : agent!.color
  const avatarText = isUser ? (me ? initials(me.name) : currentUser.initials) : agent!.name.charAt(0)
  const label = kindLabel[message.kind]
  return (
    <article className={styles.msg}>
      <span className={styles.avatar} style={{ background: color }}>{avatarText}</span>
      <div className={styles.main}>
        <header>
          <strong>{name}</strong>
          <time>{message.time}</time>
          {label && <span className={styles.kind}>{label}</span>}
        </header>
        <p className={message.kind === 'tool_call' || message.kind === 'tool_result' ? styles.mono : ''}>{message.body}</p>
      </div>
    </article>
  )
}
