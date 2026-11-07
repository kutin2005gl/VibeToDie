import { Fragment, type ReactNode } from 'react'
import Link from 'next/link'
import { Breadcrumb, BreadcrumbBack, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '../../components/ui/breadcrumb'
import { ChevronRight } from '../../components/icons'
import { PageHeader } from '../../components/PageHeader'
import type { User } from '../../api/auth'
import { departmentLabel, initials, knownDepartments } from '../../shell/labels'
import { UNKNOWN_DEPARTMENT, type DepartmentUsage, type RoomSummary, type Usage, type UserUsage } from '../../api/admin'
import { RememberUsers } from './userNames'
import styles from './AdminTrace.module.css'

// Màn quản trị: chi phí theo phòng ban → nhân viên → room → diễn tiến đầy đủ của room (TraceView).
// Các view nhận dữ liệu đã lấy trên server (src/server/admin.ts) nên render được ngay trên server.

export const departmentName = (d: string) => (d === UNKNOWN_DEPARTMENT ? 'Chưa rõ' : departmentLabel(d))

/** `$ —` khi có lượt gọi model chưa có giá và chưa tính được đồng nào; `*` khi chỉ tính được một phần. */
export function cost(u: Pick<Usage, 'cost_usd' | 'unpriced_calls'>) {
  if (u.unpriced_calls > 0 && u.cost_usd === 0) return '$ —'
  const n = u.cost_usd
  return `$${n.toFixed(n !== 0 && n < 1 ? 4 : 2)}${u.unpriced_calls > 0 ? '*' : ''}`
}

export const tokens = (n: number) => Math.round(n).toLocaleString('vi-VN')

// Giờ Việt Nam cố định: trang render trên server, mà server chạy theo UTC
export const when = (iso: string) =>
  new Date(iso).toLocaleString('vi-VN', {
    hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Asia/Ho_Chi_Minh',
  })

const total = <T extends Usage>(rows: T[]): Usage => ({
  input_tokens: rows.reduce((s, r) => s + r.input_tokens, 0),
  output_tokens: rows.reduce((s, r) => s + r.output_tokens, 0),
  cost_usd: rows.reduce((s, r) => s + r.cost_usd, 0),
  unpriced_calls: rows.reduce((s, r) => s + r.unpriced_calls, 0),
})

// Mắt xích cuối là trang đang xem; nút mũi tên lùi về mắt xích ngay trước nó. Màn hẹp chỉ giữ nút và mắt xích cuối.
export function Crumbs({ department, user, room }: { department?: string; user?: { id: string; name: string }; room?: string }) {
  const items: { label: string; href: string }[] = [{ label: 'Phòng ban', href: '/sessions' }]
  if (department !== undefined) {
    items.push({ label: departmentName(department), href: `/sessions/${encodeURIComponent(department)}` })
  }
  if (department !== undefined && user) {
    items.push({ label: user.name, href: `/sessions/${encodeURIComponent(department)}/${encodeURIComponent(user.id)}` })
  }
  if (room) items.push({ label: room, href: '' })
  const parent = items.at(-2)
  return (
    <Breadcrumb>
      {parent && <BreadcrumbBack href={parent.href} label={parent.label} />}
      <BreadcrumbList>
        {items.map((item, i) => {
          const last = i === items.length - 1
          return (
            <Fragment key={i}>
              <BreadcrumbItem className={last ? undefined : 'max-sm:hidden'}>
                {last ? <BreadcrumbPage>{item.label}</BreadcrumbPage> : <BreadcrumbLink href={item.href}>{item.label}</BreadcrumbLink>}
              </BreadcrumbItem>
              {!last && <BreadcrumbSeparator className="max-sm:hidden" />}
            </Fragment>
          )
        })}
      </BreadcrumbList>
    </Breadcrumb>
  )
}

/** Trang không lấy được dữ liệu (không phải admin, quá tải, máy chủ lỗi): nói lý do thay vì vỡ. */
export function AdminFailed({ title, message, crumbs }: { title: string; message: string; crumbs: ReactNode }) {
  return (
    <>
      <PageHeader title={title} />
      <div className={styles.body}>
        {crumbs}
        <p className={styles.error}>{message}</p>
      </div>
    </>
  )
}


const MEMBERS_SHOWN = 5

function DepartmentCard({ usage, members, share }: { usage: DepartmentUsage; members: User[]; share: number }) {
  const idle = members.length === 0 && usage.sessions === 0
  const rest = members.length - MEMBERS_SHOWN
  return (
    <Link href={`/sessions/${encodeURIComponent(usage.department)}`} className={`${styles.dept} ${idle ? styles.deptIdle : ''}`}>
      <header className={styles.deptHead}>
        <h2>{departmentName(usage.department)}</h2>
        <span>{members.length} nhân viên</span>
      </header>
      <div className={styles.deptSpend}>
        <p className={styles.deptCost}>{cost(usage)}</p>
        <div className={styles.share} role="img" aria-label={`${Math.round(share * 100)}% tổng chi phí`}>
          <i style={{ width: `${share * 100}%` }} />
        </div>
        <span className={styles.dim}>{Math.round(share * 100)}% tổng chi phí</span>
      </div>
      <dl className={styles.deptStats}>
        <div><dt>Room</dt><dd>{usage.sessions}</dd></div>
        <div><dt>Input</dt><dd>{tokens(usage.input_tokens)}</dd></div>
        <div><dt>Output</dt><dd>{tokens(usage.output_tokens)}</dd></div>
      </dl>
      {members.length > 0 ? (
        <ul className={styles.members} aria-label="Nhân viên">
          {members.slice(0, MEMBERS_SHOWN).map((m) => <li key={m.id} title={m.name || m.email}>{initials(m.name || m.email)}</li>)}
          {rest > 0 && <li className={styles.more}>+{rest}</li>}
        </ul>
      ) : (
        <p className={styles.dim}>Chưa có nhân viên</p>
      )}
      <span className={styles.deptGo} aria-hidden="true">Xem nhân viên <ChevronRight size={14} /></span>
    </Link>
  )
}

export function DepartmentsView({ usage, users }: { usage: DepartmentUsage[]; users: User[] }) {
  // Mọi phòng ban, kể cả chưa có ai hay chưa có room nào; cộng phòng ban lạ có trong dữ liệu
  const names = [...new Set([...knownDepartments, ...users.flatMap((u) => u.departments), ...usage.map((u) => u.department)])]
  const rows: DepartmentUsage[] = names.map((d) => usage.find((u) => u.department === d)
    ?? { department: d, sessions: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0, unpriced_calls: 0 })
  rows.sort((a, b) => b.cost_usd - a.cost_usd || b.sessions - a.sessions)
  const all = total(usage)

  return (
    <>
      <PageHeader title="Phiên làm việc" />
      <div className={styles.body}>
        <Crumbs />
        <p className={styles.overview}>
          <b>{cost(all)}</b>
          <span>tổng chi phí của {names.length} phòng ban · {tokens(all.input_tokens)} → {tokens(all.output_tokens)} tokens</span>
        </p>
        <div className={styles.deptGrid}>
          {rows.map((r) => (
            <DepartmentCard key={r.department} usage={r}
              members={users.filter((u) => u.departments.includes(r.department))}
              share={all.cost_usd > 0 ? r.cost_usd / all.cost_usd : 0} />
          ))}
        </div>
      </div>
    </>
  )
}

export function DepartmentUsersView({ department, usage, users }: { department: string; usage: UserUsage[]; users: User[] }) {
  const byId = new Map(users.map((u) => [u.id, u]))
  // Người đang thuộc phòng ban, cộng người đã chuyển đi nhưng còn room tính cho phòng ban này
  const ids = [...new Set([...users.filter((u) => u.departments.includes(department)).map((u) => u.id), ...usage.map((u) => u.user_id)])]
  const rows: (UserUsage & { user?: User })[] = ids.map((id) => ({
    ...(usage.find((u) => u.user_id === id)
      ?? { user_id: id, sessions: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0, unpriced_calls: 0 }),
    user: byId.get(id),
  }))
  rows.sort((a, b) => b.cost_usd - a.cost_usd)
  const all = total(usage)
  const rooms = usage.reduce((s, u) => s + u.sessions, 0)

  return (
    <>
      <PageHeader title={`Phòng ban ${departmentName(department)}`} />
      <div className={styles.body}>
        <Crumbs department={department} />
        <RememberUsers users={rows.map((r) => ({ id: r.user_id, name: r.user?.name || r.user?.email || r.user_id }))} />
        <p className={styles.overview}>
          <b>{cost(all)}</b>
          <span>
            chi phí của {departmentName(department)} · {rows.length} nhân viên · {rooms} room
            · {tokens(all.input_tokens)} → {tokens(all.output_tokens)} tokens
          </span>
        </p>
        {rows.length === 0 ? (
          <p className={styles.muted}>Phòng ban này chưa có nhân viên nào.</p>
        ) : (
          <ul className={styles.people}>
            {rows.map((r) => {
              const name = r.user?.name || r.user?.email || r.user_id
              const share = all.cost_usd > 0 ? r.cost_usd / all.cost_usd : 0
              return (
                <li key={r.user_id}>
                  <Link href={`/sessions/${encodeURIComponent(department)}/${encodeURIComponent(r.user_id)}`}
                        className={`${styles.person} ${r.sessions === 0 ? styles.personIdle : ''}`}>
                    <span className={styles.avatar} aria-hidden="true">{initials(name)}</span>
                    <span className={styles.personName}>
                      <strong>
                        {name}
                        {r.user && !r.user.departments.includes(department) && <span className={styles.badge}>đã rời phòng ban</span>}
                      </strong>
                      <small>{r.user?.email ?? r.user_id}</small>
                    </span>
                    <span className={styles.personStat}>
                      <b>{r.sessions}</b> room
                    </span>
                    <span className={styles.personStat}>
                      {tokens(r.input_tokens)} → {tokens(r.output_tokens)} tokens
                    </span>
                    <span className={styles.personCost}>
                      <b>{cost(r)}</b>
                      <span className={styles.share} role="img" aria-label={`${Math.round(share * 100)}% chi phí của phòng ban`}>
                        <i style={{ width: `${share * 100}%` }} />
                      </span>
                    </span>
                    <ChevronRight size={16} className={styles.personGo} />
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </>
  )
}

export const statusLabel: Record<RoomSummary['status'], string> = {
  running: 'Đang chạy', waiting: 'Chờ nhân viên', done: 'Xong', failed: 'Không hoàn thành',
}

/** Tên hiển thị của một tài khoản, hoặc id nếu user-service không còn tài khoản đó. */
export const userName = (users: User[], userId: string) => {
  const user = users.find((u) => u.id === userId)
  return user?.name || user?.email || userId
}

const VN = 'Asia/Ho_Chi_Minh'
const dayKey = (d: Date) => d.toLocaleDateString('en-CA', { timeZone: VN }) // YYYY-MM-DD theo giờ Việt Nam
const clockVN = (iso: string) => new Date(iso).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: VN })

function dayLabel(key: string) {
  if (key === dayKey(new Date())) return 'Hôm nay'
  if (key === dayKey(new Date(Date.now() - 86_400_000))) return 'Hôm qua'
  const label = new Date(`${key}T12:00:00+07:00`).toLocaleDateString('vi-VN', {
    weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric', timeZone: VN,
  })
  return label.charAt(0).toUpperCase() + label.slice(1)
}

// Thứ tự trên thanh trạng thái: việc xong trước, việc dở sau
const STATUS_ORDER: RoomSummary['status'][] = ['done', 'waiting', 'running', 'failed']

const toneClass: Record<RoomSummary['status'], string> = {
  done: styles.toneDone, waiting: styles.toneWaiting, running: styles.toneRunning, failed: styles.toneFailed,
}

/**
 * Room của một nhân viên như một dòng thời gian: nhóm theo ngày, mỗi room là một mốc có chấm màu theo
 * trạng thái, và chi phí so với room tốn nhất của người này.
 */
export function UserRoomsView({ department, userId, rooms, users }: {
  department: string; userId: string; rooms: RoomSummary[]; users: User[]
}) {
  const user = users.find((u) => u.id === userId)
  const name = userName(users, userId)
  const all = total(rooms)
  const most = Math.max(...rooms.map((r) => r.cost_usd), 0)
  const counts = STATUS_ORDER.map((s) => ({ status: s, n: rooms.filter((r) => r.status === s).length })).filter((c) => c.n)
  const days: { key: string; rooms: RoomSummary[] }[] = []
  for (const r of rooms) {
    const key = dayKey(new Date(r.updated_at))
    if (days[days.length - 1]?.key !== key) days.push({ key, rooms: [] })
    days[days.length - 1].rooms.push(r)
  }

  return (
    <>
      <PageHeader title={name} />
      <div className={styles.body}>
        <Crumbs department={department} user={{ id: userId, name }} />
        <RememberUsers users={[{ id: userId, name }]} />

        <section className={styles.profile} aria-label="Nhân viên">
          <span className={styles.profileAvatar} aria-hidden="true">{initials(name)}</span>
          <div className={styles.profileWho}>
            <h2>{name}</h2>
            <p>
              {user?.email ?? userId}
              {user?.departments.map((d) => <span key={d} className={styles.badge}>{departmentName(d)}</span>)}
            </p>
          </div>
          <div className={styles.profileSpend}>
            <b>{cost(all)}</b>
            <span>{rooms.length} room · {tokens(all.input_tokens)} → {tokens(all.output_tokens)} tokens</span>
          </div>
          {counts.length > 0 && (
            <div className={styles.mix}>
              <div className={styles.mixBar} role="img"
                   aria-label={counts.map((c) => `${c.n} ${statusLabel[c.status]}`).join(', ')}>
                {counts.map((c) => <i key={c.status} className={toneClass[c.status]} style={{ flexGrow: c.n }} />)}
              </div>
              <ul className={styles.mixLegend}>
                {counts.map((c) => (
                  <li key={c.status} className={toneClass[c.status]}><b>{c.n}</b> {statusLabel[c.status]}</li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {rooms.length === 0 && <p className={styles.muted}>Nhân viên này chưa chat room nào.</p>}
        {days.map((day) => {
          const spent = total(day.rooms)
          return (
            <section key={day.key} className={styles.day}>
              <h3 className={styles.dayHead}>
                {dayLabel(day.key)}
                <span>{day.rooms.length} room · {cost(spent)}</span>
              </h3>
              <ol className={styles.timeline}>
                {day.rooms.map((r) => (
                  <li key={r.id} className={`${styles.entry} ${toneClass[r.status]} ${r.deleted_at ? styles.entryDeleted : ''}`}>
                    <time className={styles.entryTime} dateTime={r.updated_at}>{clockVN(r.updated_at)}</time>
                    <span className={styles.entryDot} aria-hidden="true" />
                    <Link className={styles.entryCard}
                          href={`/sessions/${encodeURIComponent(department)}/${encodeURIComponent(userId)}/${r.id}`}>
                      <span className={styles.entryMain}>
                        <strong>{r.title}</strong>
                        <span className={styles.entryMeta}>
                          <span className={styles.entryStatus}>{statusLabel[r.status]}</span>
                          <span>{r.runs} lượt chạy</span>
                          <span>{tokens(r.input_tokens)} → {tokens(r.output_tokens)} tokens</span>
                          {r.deleted_at && <span className={styles.badge}>nhân viên đã xóa</span>}
                        </span>
                      </span>
                      <span className={styles.entryCost}>
                        <b>{cost(r)}</b>
                        <span className={styles.share} role="img" aria-label={`${Math.round(most > 0 ? (r.cost_usd / most) * 100 : 0)}% so với room tốn nhất`}>
                          <i style={{ width: `${most > 0 ? (r.cost_usd / most) * 100 : 0}%` }} />
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            </section>
          )
        })}
      </div>
    </>
  )
}
