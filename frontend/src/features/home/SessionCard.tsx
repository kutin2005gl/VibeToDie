import { Archive, FolderPlus, SquareArrowOutUpRight, Send, Undo2 } from '../../components/icons'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Avatar, AvatarStack } from '../../components/Avatar'
import { ListSelect } from '../../components/ListSelect'
import { agentById } from '../../mocks/agents'
import type { MockSession } from '../../mocks/home'
import styles from './SessionCard.module.css'

function ActivitySparkline({ values }: { values: number[] }) {
  return (
    <div className={styles.spark}>
      <div className={styles.bars}>
        {values.map((v, i) => <i key={i} style={{ height: `${Math.max(v, 0.06) * 100}%` }} />)}
      </div>
      <div className={styles.axis}><span>30p</span><span>15p</span><span>nay</span></div>
    </div>
  )
}

// Thẻ có hai mặt: bấm để lật sang mặt sau (nhắn thẳng cho Điều phối), nút hoàn tác hoặc Esc để lật lại.
export function SessionCard({ session }: { session: MockSession }) {
  const pct = (session.doneTasks / session.totalTasks) * 100
  const [flipped, setFlipped] = useState(false)
  const [message, setMessage] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const agents = session.agentIds.map(agentById)
  const [target, setTarget] = useState(agents[0].id)

  useEffect(() => {
    if (flipped) inputRef.current?.focus({ preventScroll: true })
  }, [flipped])

  const flipBack = () => setFlipped(false)

  // TODO: gửi tin thật qua API; hiện chỉ xoá nội dung và lật lại.
  const send = () => {
    if (!message.trim()) return
    setMessage('')
    flipBack()
  }

  const onFrontKey = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setFlipped(true)
    }
  }

  const onBackKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') flipBack()
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className={styles.scene}>
      <div className={`${styles.inner} ${flipped ? styles.flipped : ''}`}>
        <article
          className={`${styles.face} ${styles.front}`}
          tabIndex={flipped ? -1 : 0}
          role="button"
          aria-label={`${session.title} — bấm để nhắn tin`}
          inert={flipped}
          onClick={() => setFlipped(true)}
          onKeyDown={onFrontKey}
        >
          <h3>{session.title}</h3>
          <p>{session.summary}</p>
          <div className={styles.tools} onClick={(e) => e.stopPropagation()}>
            <button aria-label="Mở phiên"><SquareArrowOutUpRight size={14} /></button>
            <button aria-label="Lưu trữ"><Archive size={14} /></button>
            <button aria-label="Thêm vào thư mục"><FolderPlus size={14} /></button>
          </div>
          <ActivitySparkline values={session.activity} />
          <footer>
            <AvatarStack agents={agents} max={3} />
            <span>{session.doneTasks}/{session.totalTasks} việc</span>
          </footer>
          <div className={styles.progress}><div style={{ width: `${pct}%` }} /></div>
        </article>

        <section className={`${styles.face} ${styles.back}`} inert={!flipped} aria-label={`Nhắn tin cho ${session.title}`} onKeyDown={onBackKey}>
          <header>
            <h3>{session.title}</h3>
            <button className={styles.undo} aria-label="Lật lại" onClick={flipBack}><Undo2 size={14} /></button>
          </header>
          <textarea
            ref={inputRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Nhắn cho Điều phối…"
            aria-label="Tin nhắn"
          />
          <footer>
            <ListSelect
              ghost
              placement="up"
              label="Gửi cho agent"
              value={target}
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
              onChange={setTarget}
              icon={<Avatar agent={agentById(target)} size={16} />}
            />
            <button className={styles.send} aria-label="Gửi" disabled={!message.trim()} onClick={send}>
              <Send size={14} />
            </button>
          </footer>
        </section>
      </div>
    </div>
  )
}
