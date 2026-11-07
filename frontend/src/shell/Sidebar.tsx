import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { AnimatePresence, MotionConfig, motion, type Transition } from 'motion/react'
import {
  BarChart3, BookOpen, Bot, Bots, ChevronDown, Contact, Home, MessagesSquare, PanelLeft, Plus, Radar,
  SessionTrace, Settings, StateDone, StateFailed, StateRunning, StateWaiting, Trash2, type IconComponent,
} from '../components/icons'
import { primaryNav, networkNav, staffNav, type NavId } from '../mocks/nav'
import { pendingItem, statusText, type RequestStatus } from '../mocks/staff'
import { BrandLogo } from './BrandMark'
import { useRole } from './session'
import { useStore } from './store'
import styles from './Sidebar.module.css'

const icons: Record<NavId, IconComponent> = {
  home: Home, agents: Bots, teams: Bots, rooms: SessionTrace,
  analytics: BarChart3, sonar: Radar, contacts: Contact,
  requests: MessagesSquare, skills: Bot,
}

// Cùng spring với Highlight của animate-ui (sidebar của fiurozz-fe).
const spring: Transition = { type: 'spring', stiffness: 350, damping: 35 }

// Trạng thái của room: đang chạy (vòng xoay), chờ bạn, xong, không hoàn thành.
const stateIcons: Record<RequestStatus, IconComponent> = {
  running: StateRunning, waiting: StateWaiting, done: StateDone, failed: StateFailed,
}

// Xóa room bằng hai lần bấm: lần đầu đổi thành "Xóa?", lần hai mới xóa; rời chuột hay quá 3 giây thì thôi.
function DeleteRoom({ title, onDelete }: { title: string; onDelete: () => Promise<void> }) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!armed) return
    const timer = setTimeout(() => setArmed(false), 3000)
    return () => clearTimeout(timer)
  }, [armed])
  return (
    <button
      className={`${styles.delete} ${armed ? styles.armed : ''}`}
      aria-label={armed ? `Bấm lần nữa để xóa room ${title}` : `Xóa room ${title}`}
      title={armed ? 'Bấm lần nữa để xóa' : 'Xóa room'}
      disabled={busy}
      onMouseLeave={() => setArmed(false)}
      onClick={() => {
        if (!armed) return setArmed(true)
        setBusy(true)
        onDelete().catch(() => { setBusy(false); setArmed(false) })
      }}
    >
      {armed ? <span>Xóa?</span> : <Trash2 size={14} />}
    </button>
  )
}

interface Props {
  collapsed: boolean
  onToggle: () => void
}

interface Tip { label: string; top: number; left: number }
interface Box { top: number; height: number }

interface ItemProps {
  to: string
  label: string
  Icon: IconComponent
  collapsed: boolean
  onHover: (el: HTMLElement) => void
}

function Item({ to, label, Icon, collapsed, onHover }: ItemProps) {
  // Như NavLink: mục /agents vẫn sáng khi đang ở /agents/:id.
  const pathname = usePathname()
  const isActive = pathname === to || pathname.startsWith(`${to}/`)
  return (
    <Link
      href={to}
      aria-label={collapsed ? label : undefined}
      className={`${styles.item} ${isActive ? styles.active : ''}`}
      onMouseEnter={(e) => onHover(e.currentTarget)}
      onFocus={(e) => onHover(e.currentTarget)}
    >
      <Icon size={17} className={styles.icon} />
      <span className={styles.label}>{label}</span>
    </Link>
  )
}

function Group({ children }: { children: ReactNode }) {
  return <nav className={styles.group}>{children}</nav>
}

export function Sidebar({ collapsed, onToggle }: Props) {
  const asideRef = useRef<HTMLElement>(null)
  // Một nền highlight duy nhất ở cấp sidebar (như mode "parent" của animate-ui):
  // không gỡ/gắn lại khi đổi mục nên không chớp, chỉ spring tới vị trí mục mới.
  const [box, setBox] = useState<Box | null>(null)
  const [visible, setVisible] = useState(false)
  const [tip, setTip] = useState<Tip | null>(null)

  function hover(el: HTMLElement) {
    const aside = asideRef.current!.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    setBox({ top: r.top - aside.top, height: r.height })
    setVisible(true)
    if (!collapsed) return setTip(null)
    setTip({ label: el.getAttribute('aria-label') ?? '', top: r.top + r.height / 2, left: r.right + 8 })
  }

  function leave() {
    setVisible(false)
    setTip(null)
  }

  // Đổi độ rộng thì vị trí cũ không còn đúng: ẩn đi, lần hover sau đo lại.
  useEffect(leave, [collapsed])

  const router = useRouter()
  const navigate = (to: string) => router.push(to)
  const onSessions = usePathname() === '/rooms'
  const role = useRole()
  const { requests, activeRequestId, setActiveRequestId, removeRequest } = useStore()
  // Lịch sử room xổ ra ngay dưới mục "Room", thay cho cột danh sách riêng.
  const [sessionsOpen, setSessionsOpen] = useState(true)
  // Danh sách cuộn được mà chưa tới đáy thì mờ dần ở đáy, thay cho thanh cuộn và mục bị cắt nửa chừng
  const listRef = useRef<HTMLDivElement>(null)
  const [more, setMore] = useState(false)
  const measure = () => {
    const el = listRef.current
    setMore(!!el && el.scrollTop + el.clientHeight < el.scrollHeight - 2)
  }
  useEffect(measure, [requests.length, sessionsOpen])
  const openSession = (id: string) => { setActiveRequestId(id); navigate('/rooms') }
  const item = (to: string, label: string, Icon: IconComponent) => (
    <Item key={to} to={to} label={label} Icon={Icon} collapsed={collapsed} onHover={hover} />
  )

  return (
    <MotionConfig reducedMotion="user">
      <aside
        ref={asideRef}
        className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}
        onMouseLeave={leave}
        onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) leave() }}
      >
        {box && (
          <motion.span
            className={styles.highlight}
            aria-hidden="true"
            // Lần đầu hiện thì đặt ngay tại mục, các lần sau mới trượt.
            initial={{ ...box, opacity: 0 }}
            animate={{ ...box, opacity: visible ? 1 : 0 }}
            transition={{ ...spring, opacity: { duration: 0.15 } }}
          />
        )}
        <div className={styles.head}>
          <span className={styles.brand}>
            <BrandLogo height={38} />
          </span>
          <button className={styles.toggle} onClick={onToggle} aria-label="Thu gọn/mở thanh bên (Ctrl+B)">
            <span className={styles.mark}><BrandLogo height={20} /></span>
            <PanelLeft size={17} className={styles.panel} />
          </button>
        </div>
        {/* Admin cũng có room riêng: mục "Room" nằm ngay dưới "Trang chủ", trước các màn quản trị. */}
        <Group>
            {role !== 'staff' && item(primaryNav[0].path, primaryNav[0].label, icons[primaryNav[0].id])}
            {/* Bấm cả thanh để mở/đóng lịch sử; thu gọn thì không có chỗ xổ nên đi thẳng tới room đang mở. */}
            <button
              className={`${styles.item} ${styles.parent} ${sessionsOpen ? styles.open : ''} ${onSessions && (collapsed || !sessionsOpen) ? styles.active : ''}`}
              aria-label={collapsed ? staffNav[0].label : undefined}
              aria-expanded={collapsed ? undefined : sessionsOpen}
              onMouseEnter={(e) => hover(e.currentTarget)}
              onFocus={(e) => hover(e.currentTarget)}
              onClick={() => (collapsed ? navigate('/rooms') : setSessionsOpen((o) => !o))}
            >
              <MessagesSquare size={17} className={styles.icon} />
              <span className={styles.label}>{staffNav[0].label}</span>
              <ChevronDown size={15} className={styles.caret} aria-hidden="true" />
            </button>
            <AnimatePresence initial={false}>
              {sessionsOpen && !collapsed && (
                <motion.div
                  key="sessions"
                  className={styles.sub}
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={spring}
                >
                  <div
                    ref={listRef}
                    className={`${styles.subList} ${more ? styles.more : ''} ${role === 'staff' ? '' : styles.admin}`}
                    // Nền hover đo theo vị trí lúc rê chuột: cuộn thì nó lệch khỏi mục, nên ẩn đi
                    onScroll={() => { leave(); measure() }}
                  >
                    <button
                      className={`${styles.subItem} ${onSessions && !activeRequestId ? styles.active : ''}`}
                      onMouseEnter={(e) => hover(e.currentTarget)}
                      onFocus={(e) => hover(e.currentTarget)}
                      onClick={() => openSession('')}
                    >
                      <span className={styles.slot}><Plus size={15} /></span>
                      <span className={styles.subLabel}>Room mới</span>
                    </button>
                    {requests.map((r) => {
                      const state = pendingItem(r) ? 'waiting' : r.status
                      const StateIcon = stateIcons[state]
                      return (
                        <div key={r.id} className={styles.subRow}>
                          <button
                            className={`${styles.subItem} ${onSessions && r.id === activeRequestId ? styles.active : ''}`}
                            title={`${r.title} · ${statusText(r)}`}
                            onMouseEnter={(e) => hover(e.currentTarget)}
                            onFocus={(e) => hover(e.currentTarget)}
                            onClick={() => openSession(r.id)}
                          >
                            <span className={`${styles.slot} ${styles[state]}`} role="img" aria-label={statusText(r)}>
                              <StateIcon size={15} />
                            </span>
                            <span className={styles.subLabel}>{r.title}</span>
                          </button>
                          {/* Room đang chạy vẫn còn lượt chạy sẽ lưu vào nó: chưa cho xóa */}
                          {state !== 'running' && !r.id.startsWith('tmp') && (
                            <DeleteRoom title={r.title} onDelete={() => removeRequest(r.id)} />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            {role !== 'staff' && primaryNav.slice(1).map((n) => item(n.path, n.label, icons[n.id]))}
            {/* Agent riêng là của tài khoản, nên admin cũng có (cùng trang với nhân viên) */}
            {item('/skills', staffNav[1].label, icons.skills)}
        </Group>
        {role !== 'staff' && (
          <>
            <div className={styles.groupHeader} aria-hidden={collapsed}><span>NETWORK</span><i /></div>
            <Group>{networkNav.map((n) => item(n.path, n.label, icons[n.id]))}</Group>
          </>
        )}
        <div className={styles.spacer} />
        <Group>
          {item('/docs', 'Hướng dẫn', BookOpen)}
          {item('/settings', 'Cài đặt', Settings)}
        </Group>
        <button className={styles.rail} onClick={onToggle} tabIndex={-1} aria-label="Thu gọn/mở thanh bên" title="Thu gọn/mở thanh bên" />
      </aside>
      {createPortal(
        <AnimatePresence>
          {tip && (
            <motion.div
              key="sidebar-tip"
              role="tooltip"
              className={styles.tip}
              style={{ top: tip.top, left: tip.left }}
              initial={{ opacity: 0, scale: 0.9, x: -6, y: '-50%' }}
              animate={{ opacity: 1, scale: 1, x: 0, y: '-50%' }}
              exit={{ opacity: 0, scale: 0.9, x: -6, y: '-50%' }}
              transition={spring}
            >
              <motion.span key={tip.label} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={spring}>
                {tip.label}
              </motion.span>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </MotionConfig>
  )
}
