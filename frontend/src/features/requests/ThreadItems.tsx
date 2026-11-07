import { useEffect, useState, useSyncExternalStore } from 'react'
import { agentIcons, Bot, Check, ChevronRight, Mail, Pause, RefreshCw, Send, ShieldCheck, Sparkles, X } from '../../components/icons'
import { Avatar } from '../../components/Avatar'
import { Button } from '../../components/Button'
import { agentCatalog } from '../../mocks/agentCatalog'
import { agents } from '../../mocks/agents'
import type { Decision, MessageStatus, ParallelMember, ThreadItem, TraceStep } from '../../mocks/staff'
import styles from './ThreadItems.module.css'

interface Props {
  item: ThreadItem
  onDecide: (itemId: string, value: 'yes' | 'no') => void
  onAnswer: (body: string) => void
}

export function ThreadItemView({ item, onDecide, onAnswer }: Props) {
  switch (item.kind) {
    case 'request':
    case 'reply':
      return (
        <div className={styles.mine}>
          <p>{item.body}</p>
          <time>{item.time}</time>
        </div>
      )
    case 'route':
      return <p className={styles.route}><Bot size={15} /> {item.body}</p>
    case 'result':
      return (
        <article className={styles.result}>
          <Author name={item.agent} time={item.time} />
          <h3>{item.title}</h3>
          {item.body.map((p, i) => <p key={i}>{p}</p>)}
          {item.trace.length > 0 && <Trace steps={item.trace} tries={item.tries} />}
        </article>
      )
    case 'failed': {
      // Nhân viên tự dừng: không phải lỗi, chỉ là một dòng ghi nhận như dòng định tuyến
      if (item.stopped) return <p className={styles.route}><Pause size={14} /> {item.body} <time>{item.time}</time></p>
      // Lỗi thật: một tin của Điều phối cùng kiểu với chuỗi giao việc, gắn nhãn "Không hoàn thành"
      const { name, color, Icon } = agentLook('coordinator')
      return (
        <article className={styles.message}>
          <span className={styles.agentAvatar} style={{ color }} aria-hidden="true"><Icon size={28} /></span>
          <div className={styles.messageBody}>
            <header>
              <strong>{name}</strong>
              <time>{item.time}</time>
              <span className={styles.failedTag}><X size={12} /> Không hoàn thành</span>
            </header>
            <p>{item.body}</p>
            {item.trace.length > 0 && <Trace steps={item.trace} />}
          </div>
        </article>
      )
    }
    case 'message':
      return <AgentMessage item={item} />
    case 'parallel':
      return <Parallel item={item} />

    case 'approval': {
      // Email đã có khung xem trước; tham số thô chỉ hiện cho hành động không phải email
      const isEmail = !!item.email.body
      const badge = approvalBadge(item.decision, item.sent)
      return (
        <section className={`${styles.card} ${styles.approval} ${item.decision ? styles.settled : ''}`} aria-label="Cần bạn duyệt">
          <header>
            <span className={`${styles.ask} ${badge.tone}`}><badge.Icon size={14} /> {badge.label}</span>
            <time>{item.time}</time>
          </header>
          <h3>{item.title}</h3>
          {isEmail ? (
            <MailPreview {...item.email} tag={item.facts.find(([k]) => k === 'order_id')?.[1]} foldable={!!item.decision} />
          ) : (
            <dl className={styles.facts}>
              {item.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
            </dl>
          )}
          {item.decision ? (
            <ApprovalOutcome decision={item.decision} sent={item.sent} />
          ) : (
            // Lựa chọn xếp dọc, đánh số, như khung xin phép của Claude Code
            <div className={styles.decide}>
              <p className={styles.note}>Đồng ý thì hệ thống gửi đúng email trên cho khách, một lần. Hệ thống không chuyển tiền.</p>
              <ol className={styles.choices}>
                <li><button onClick={() => onDecide(item.id, 'yes')}><kbd>1</kbd><span>Đồng ý gửi email</span></button></li>
                <li><button onClick={() => onDecide(item.id, 'no')}><kbd>2</kbd><span>Không gửi</span></button></li>
              </ol>
            </div>
          )}
        </section>
      )
    }
    case 'skill':
      return (
        <section className={`${styles.card} ${item.decision ? styles.settled : ''}`} aria-label="Duyệt agent mới">
          <header>
            <span className={styles.ask}><Sparkles size={14} /> {item.decision ? 'Agent mới' : 'Agent mới cần bạn duyệt'}</span>
            <time>{item.time}</time>
          </header>
          <h3>{item.name}</h3>
          <p className={styles.summary}>{item.summary}</p>
          <ul className={styles.checks}>
            {item.checks.map((c) => <li key={c}><Check size={14} /> {c}</li>)}
          </ul>
          <div className={styles.tools}>
            <span>Dùng công cụ</span>
            {item.tools.map((t) => <code key={t}>{t}</code>)}
          </div>
          <p className={styles.note}>
            Đồng ý thì agent làm ngay yêu cầu này và được lưu cho riêng tài khoản của bạn. Agent không có thêm quyền đọc dữ liệu hay gọi công cụ nào ngoài quyền bạn đang có.
          </p>
          {item.decision ? (
            <Decided decision={item.decision} yes="Bạn đã đồng ý dùng agent này" no="Bạn đã bỏ agent này" />
          ) : (
            <div className={styles.actions}>
              <Button onClick={() => onDecide(item.id, 'no')}>Bỏ</Button>
              <Button variant="primary" onClick={() => onDecide(item.id, 'yes')}><Check size={15} /> Đồng ý dùng agent</Button>
            </div>
          )}
        </section>
      )
    case 'clarify':
      return <Clarify item={item} onAnswer={onAnswer} />
  }
}

// Tên, màu và icon của agent theo tên mandate; agent lạ (vd. mới tạo) dùng Bot và màu trung tính.
function agentLook(id: string) {
  const a = agentCatalog.find((c) => c.id === id)
  return { name: a?.name ?? id, color: a?.color ?? 'var(--text-muted)', Icon: agentIcons[id] ?? Bot }
}

function Mention({ agent }: { agent: string }) {
  return <span className={styles.mention}>@{agentLook(agent).name}</span>
}

const duration = (seconds: number) => {
  const s = Math.max(0, Math.round(seconds))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

// Như Codex CLI: đang làm thì "Thinking 12s" với đồng hồ chạy, xong thì đứng ở "Worked 1m 03s".
function Status({ status }: { status: MessageStatus }) {
  const live = status.seconds === undefined && status.since !== undefined
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [live])
  const seconds = live ? (now - Date.parse(status.since!)) / 1000 : status.seconds ?? 0
  return (
    <span className={`${styles.status} ${live ? styles.live : ''}`} role={live ? 'status' : undefined}>
      {status.label} {duration(seconds)}
    </span>
  )
}

// Số ký tự đã gõ của từng nội dung trong phiên này: bản lưu cuối thay cho bản live cùng nội dung thì
// gõ tiếp chỗ đang dở chứ không gõ lại, và room cũ mở lại (tin không còn mới) hiện ngay.
const typedChars = new Map<string, number>()
const FRESH_MS = 15_000
const reducedMotion = () => typeof window !== 'undefined' && (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)

// Báo cho màn room mỗi khi một tin gõ xong, để nó hiện tiếp các tin đang chờ phía sau
let typedVersion = 0
const typedListeners = new Set<() => void>()
const subscribeTyped = (f: () => void) => { typedListeners.add(f); return () => { typedListeners.delete(f) } }
export const useTypedVersion = () => useSyncExternalStore(subscribeTyped, () => typedVersion, () => typedVersion)

/** Ký tự bắt đầu gõ: tin mới tới thì từ 0 (ghi lại ngay, nên chờ lâu sau tin khác vẫn được gõ), còn lại hiện hết. */
function typedFrom(text: string, at?: string): number {
  const known = typedChars.get(text)
  if (known !== undefined) return known
  const fresh = at !== undefined && Date.now() - Date.parse(at) < FRESH_MS && !reducedMotion()
  const from = fresh ? 0 : text.length
  typedChars.set(text, from)
  return from
}

/** Tin của agent chưa gõ xong: màn room chưa hiện các tin sau nó, để từng agent nói xong mới tới agent sau. */
export function stillTyping(item: ThreadItem): boolean {
  if (item.kind !== 'message' || (item.status?.seconds === undefined && item.status?.since !== undefined)) return false
  const text = item.body.join('\n')
  return !!text && typedFrom(text, item.at) < text.length
}

/** Số ký tự của `text` đang hiện: tin vừa tới thì tăng dần như đang gõ, còn lại hiện hết ngay. */
function useTyped(text: string, at?: string): number {
  const [shown, setShown] = useState(() => (text ? typedFrom(text, at) : 0))
  useEffect(() => {
    if (shown >= text.length) return
    // Đoạn dài gõ xong trong khoảng 3 giây, đoạn ngắn không chậm hơn khoảng 80 ký tự/giây
    const step = Math.max(2, Math.ceil(text.length / 120))
    let n = shown
    // Đếm ngoài setShown: báo màn room (đổi state của nó) trong hàm cập nhật state là lỗi của React
    const timer = setInterval(() => {
      n = Math.min(text.length, n + step)
      typedChars.set(text, n)
      setShown(n)
      if (n >= text.length) {
        clearInterval(timer)
        typedVersion++
        typedListeners.forEach((f) => f())
      }
    }, 25)
    return () => clearInterval(timer)
    // Chỉ chạy lại khi nội dung đổi; `shown` là trạng thái của chính lần gõ này
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])
  return Math.min(shown, text.length)
}

// Một tin trong chuỗi giao việc, như nhóm chat: Điều phối @agent, agent trả lời lại @Điều phối.
function AgentMessage({ item }: { item: Extract<ThreadItem, { kind: 'message' }> }) {
  const { name, color, Icon } = agentLook(item.agent)
  const working = item.status?.seconds === undefined && item.status?.since !== undefined
  const text = item.body.join('\n')
  const shown = useTyped(text, item.at)
  // Bản nháp và chi tiết hiện sau khi gõ xong phần trả lời
  const typed = shown >= text.length
  return (
    <article className={styles.message}>
      <span className={styles.agentAvatar} style={{ color }} aria-hidden="true"><Icon size={28} /></span>
      <div className={styles.messageBody}>
        <header>
          <strong>{name}</strong>
          {item.to && <Mention agent={item.to} />}
          {!working && <time>{item.time}</time>}
          {item.status && !working && <Status status={item.status} />}
        </header>
        {item.work}
        {working
          ? <Status status={item.status!} />
          : text && text.slice(0, shown).split('\n').map((p, i) => <p key={i}>{p}</p>)}
        {item.mentions && (
          <ul className={styles.mentions}>
            {item.mentions.map((m, i) => <li key={i}><Mention agent={m.agent} /><span>{m.text}</span></li>)}
          </ul>
        )}
        {typed && item.drafts?.map((d, i) => (
          <div key={i} className={`${styles.email} ${styles.draft}`}>
            <div className={styles.emailHead}><Mail size={14} /> {d.title}</div>
            <p>{d.body}</p>
          </div>
        ))}
        {typed && item.details && item.details.length > 0 && <Details lines={item.details} />}
      </div>
    </article>
  )
}

// Các agent Điều phối giao chạy cùng lúc: thẻ cạnh nhau, mỗi thẻ một đồng hồ riêng, màn hẹp thì xuống dòng.
function Parallel({ item }: { item: Extract<ThreadItem, { kind: 'parallel' }> }) {
  const working = item.members.some((m) => m.state === 'working')
  // Đang làm thì ParallelRail (sticky bên phải) đã hiện; khung này chỉ đứng lại làm bản ghi khi xong
  if (working) return null
  return (
    <section className={styles.parallel} aria-label="Các agent làm song song">
      <header>
        <span>{working ? 'Đang làm song song' : 'Đã làm song song'} · {item.members.length} agent</span>
        <time>{item.time}</time>
      </header>
      <div className={styles.parallelGrid}>
        {item.members.map((m) => <ParallelCard key={m.id} member={m} />)}
      </div>
    </section>
  )
}

/** Khung song song đang chạy: nếu có thì room dán nó sticky bên phải để theo dõi không phải cuộn. */
export const workingGroup = (items: ThreadItem[]) =>
  [...items].reverse().find((i): i is Extract<ThreadItem, { kind: 'parallel' }> =>
    i.kind === 'parallel' && i.members.some((m) => m.state === 'working'))

export function ParallelRail({ item }: { item: Extract<ThreadItem, { kind: 'parallel' }> }) {
  const [open, setOpen] = useState(true)
  const working = item.members.filter((m) => m.state === 'working').length
  return (
    <aside className={styles.rail} aria-label="Các agent đang làm cùng lúc">
      <div className={styles.railBody}>
        <button className={styles.railToggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <ChevronRight size={14} className={open ? styles.turned : ''} />
          <strong>Cùng lúc · {item.members.length} agent</strong>
          <span>{working} đang làm</span>
        </button>
        {open
          ? item.members.map((m) => <ParallelCard key={m.id} member={m} />)
          : (
            <ul className={styles.railHeads}>
              {item.members.map((m) => {
                const { name, color, Icon } = agentLook(m.agent)
                return <li key={m.id} title={`${name}: ${m.label}`} data-state={m.state} style={{ color }}><Icon size={18} /></li>
              })}
            </ul>
          )}
      </div>
    </aside>
  )
}

function ParallelCard({ member }: { member: ParallelMember }) {
  const { name, color, Icon } = agentLook(member.agent)
  return (
    <div className={styles.parallelCard} data-state={member.state}>
      <div className={styles.parallelHead}>
        <span style={{ color }} aria-hidden="true"><Icon size={18} /></span>
        <strong>{name}</strong>
      </div>
      <p>{member.label}</p>
      {member.state === 'working' && <Status status={{ label: 'Working', since: member.since }} />}
      {member.state === 'done' && <span className={styles.parallelDone}><Check size={12} /> Đã trả lời {duration(member.seconds ?? 0)}</span>}
      {member.state === 'failed' && <span className={styles.parallelFailed}><X size={12} /> Không xong</span>}
    </div>
  )
}

/**
 * Điều phối hỏi lại, như khung hỏi của Claude Code: một khối gọn có vạch nhấn bên trái, lựa chọn
 * (nếu có) đánh số để bấm, và ô trả lời ngay trong khung. Trả lời xong thì khối lắng xuống thành
 * bản ghi: câu hỏi mờ đi, câu trả lời kèm dấu tích.
 */
function Clarify({ item, onAnswer }: { item: Extract<ThreadItem, { kind: 'clarify' }>; onAnswer: (body: string) => void }) {
  const { name, color, Icon } = agentLook('coordinator')
  const [text, setText] = useState('')
  const answered = !!item.answer
  const send = (body: string) => {
    const b = body.trim()
    if (!b || answered) return
    onAnswer(b)
    setText('')
  }
  return (
    <article className={styles.message}>
      <span className={styles.agentAvatar} style={{ color }} aria-hidden="true"><Icon size={28} /></span>
      <div className={styles.messageBody}>
        <header>
          <strong>{name}</strong>
          <time>{item.time}</time>
          {!answered && <span className={styles.ask}>Cần bạn trả lời</span>}
        </header>
        <section className={`${styles.question} ${answered ? styles.answered : ''}`} aria-label="Câu hỏi của Điều phối">
          <p className={styles.questionText}>{item.question}</p>
          {item.options.length > 0 && (
            <ol className={styles.choices}>
              {item.options.map((o, i) => (
                <li key={o}>
                  <button className={item.answer === o ? styles.picked : ''} disabled={answered} onClick={() => send(o)}>
                    <kbd>{i + 1}</kbd><span>{o}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
          {answered ? (
            <p className={styles.answerLine}><Check size={14} /><span>{item.answer}</span></p>
          ) : (
            <div className={styles.answerBox}>
              <textarea
                rows={1}
                value={text}
                aria-label="Câu trả lời"
                placeholder={item.options.length ? 'Hoặc nhập câu trả lời khác…' : 'Nhập câu trả lời…'}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send(text)
                  }
                }}
              />
              <button className={styles.answerSend} aria-label="Gửi câu trả lời" disabled={!text.trim()} onClick={() => send(text)}>
                <Send size={15} />
              </button>
            </div>
          )}
        </section>
      </div>
    </article>
  )
}

// Phần chi tiết của câu trả lời (các phát hiện kèm số liệu), gập mặc định cho dễ đọc.
function Details({ lines }: { lines: string[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={styles.trace}>
      <button className={styles.traceToggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ChevronRight size={14} className={open ? styles.turned : ''} />
        Chi tiết
      </button>
      {open && <div className={styles.details}>{lines.map((l, i) => <p key={i}>{l}</p>)}</div>}
    </div>
  )
}

function Author({ name, time }: { name: string; time: string }) {
  const agent = agents.find((a) => a.name === name)
  return (
    <header className={styles.author}>
      {agent ? <Avatar agent={agent} size={22} /> : <span className={styles.system}><Bot size={14} /></span>}
      <strong>{name}</strong>
      <time>{time}</time>
    </header>
  )
}

type Sent = 'sending' | 'done' | 'failed'

// Hệ thống không tự gửi lại (FR-19): lỗi hay chưa rõ thì nhân viên kiểm tra rồi xử lý tay
const sentText: Record<Sent, { title: string; hint?: string }> = {
  done: { title: 'Đã gửi email cho khách' },
  sending: { title: 'Chưa rõ email đã đi chưa', hint: 'Kiểm tra hộp thư đã gửi trước khi gửi lại bằng tay.' },
  failed: { title: 'Gửi email không thành công', hint: 'Hệ thống không tự gửi lại; kiểm tra rồi gửi bằng tay.' },
}

// Nhãn đầu thẻ nói luôn kết quả: chờ duyệt, đã gửi, gửi lỗi hay không gửi
function approvalBadge(decision?: Decision, sent?: Sent) {
  if (!decision) return { label: 'Cần bạn duyệt', Icon: ShieldCheck, tone: '' }
  if (decision.value === 'no') return { label: 'Không gửi', Icon: X, tone: '' }
  if (sent === 'done') return { label: 'Đã gửi', Icon: Check, tone: styles.askDone }
  if (sent === 'failed') return { label: 'Gửi lỗi', Icon: X, tone: styles.askFailed }
  return { label: 'Đã duyệt', Icon: ShieldCheck, tone: '' }
}

/** Email như khách sẽ đọc: đầu thư (người nhận, tiêu đề) rồi thân thư giữ nguyên xuống dòng. Đã duyệt thì thư dài gập bớt. */
function MailPreview({ to, subject, body, tag, foldable }: { to: string; subject: string; body: string; tag?: string; foldable: boolean }) {
  const [open, setOpen] = useState(false)
  const long = body.length > 400 || body.split('\n').length > 8
  return (
    <div className={styles.mail}>
      <div className={styles.mailTop}>
        <div className={styles.mailHead}>
          <span><Mail size={14} /> Email cho khách</span>
          {tag && <code>{tag}</code>}
        </div>
        <dl className={styles.mailMeta}>
          <dt>Đến</dt><dd>{to}</dd>
          <dt>Tiêu đề</dt><dd className={styles.mailSubject}>{subject}</dd>
        </dl>
      </div>
      <div className={styles.mailBody}>
        <p className={foldable && long && !open ? styles.clamped : undefined}>{body}</p>
        {foldable && long && (
          <button className={styles.traceToggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <ChevronRight size={14} className={open ? styles.turned : ''} />
            {open ? 'Thu gọn' : 'Xem toàn bộ'}
          </button>
        )}
      </div>
    </div>
  )
}

// Quyết định và kết quả gửi gộp thành một dòng có màu theo kết quả
function ApprovalOutcome({ decision, sent }: { decision: Decision; sent?: Sent }) {
  const at = `Bạn duyệt lúc ${decision.time}`
  const { title, hint, tone, Icon } =
    decision.value === 'no' ? { title: 'Bạn đã chọn không gửi', hint: undefined, tone: '', Icon: X }
      : !sent ? { title: 'Bạn đã đồng ý gửi', hint: undefined, tone: styles.outcomeDone, Icon: Check }
      : { ...sentText[sent], tone: { done: styles.outcomeDone, sending: styles.outcomePending, failed: styles.outcomeFailed }[sent],
          Icon: sent === 'done' ? Check : sent === 'failed' ? X : RefreshCw }
  return (
    <div className={`${styles.outcome} ${tone}`} role="status">
      <Icon size={15} />
      <strong>{title}</strong>
      <small>{[hint, decision.value === 'no' ? `Lúc ${decision.time}` : at].filter(Boolean).join(' ')}</small>
    </div>
  )
}

function Decided({ decision, yes, no }: { decision: Decision; yes: string; no: string }) {
  return (
    <p className={`${styles.decided} ${decision.value === 'yes' ? styles.yes : ''}`}>
      {decision.value === 'yes' ? <Check size={15} /> : <X size={15} />}
      {decision.value === 'yes' ? yes : no} lúc {decision.time}
    </p>
  )
}

// Diễn tiến thu gọn: ai làm, gọi công cụ gì, kiểm tra bằng code, thử lại mấy lần (FR-25).
function Trace({ steps, tries }: { steps: TraceStep[]; tries?: number }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={styles.trace}>
      <button className={styles.traceToggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ChevronRight size={14} className={open ? styles.turned : ''} />
        Diễn tiến · {steps.length} bước{tries && tries > 1 ? ` · chạy ${tries} lần` : ''}
      </button>
      {open && (
        <ol>
          {steps.map((s, i) => (
            <li key={i} className={styles[s.status]}>
              {s.status === 'ok' ? <Check size={13} /> : s.status === 'retry' ? <RefreshCw size={13} /> : <X size={13} />}
              <span>{s.agent}</span>
              {/* Lời gọi công cụ thì để mono; bước của hệ thống (kiểm tra, thử lại) là chữ thường. */}
              {s.action.includes('(') ? <code>{s.action}</code> : <em>{s.action}</em>}
              {s.note && <small>{s.note}</small>}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
