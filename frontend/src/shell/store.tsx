'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  answerSession, createSession, decideSession, deleteSession, followSession, listSessions, liveItems, messageSession, stopSession,
  toRequest, type Progress, type Session,
} from '../api/sessions'
import { getRoomDetail } from '../api/admin'
import { liveTraceItems, traceItems } from '../features/admin-trace/TraceView'
import { teams as seedTeams, type MockTeam } from '../mocks/agentCatalog'
import { agentById } from '../mocks/agents'
import { rooms as seedRooms, type MockMessage, type MockRoom } from '../mocks/rooms'
import { pendingItem, type StaffRequest, type ThreadItem } from '../mocks/staff'
import { useRole, useSession } from './session'

// Kho trạng thái dùng chung cho dữ liệu giả (đội, phiên làm việc) để Teams và Rooms thấy cùng một nguồn.
// TODO: thay bằng gọi API khi backend có endpoint teams/rooms.
interface Store {
  teams: MockTeam[]
  updateTeam: (id: string, patch: Partial<Omit<MockTeam, 'id'>>) => void
  rooms: MockRoom[]
  activeRoomId: string
  setActiveRoomId: (id: string) => void
  appendMessage: (roomId: string, msg: MockMessage) => void
  /** Tạo phiên mới có sẵn các agent đã chọn và chuyển nó thành phiên đang mở. */
  createRoom: (title: string, agentIds: string[]) => void
  /** Màn nhân viên: yêu cầu gửi cho AI và skill riêng của tài khoản. */
  requests: StaffRequest[]
  activeRequestId: string
  setActiveRequestId: (id: string) => void
  submitRequest: (body: string) => void
  reply: (requestId: string, body: string) => void
  decide: (requestId: string, itemId: string, value: 'yes' | 'no') => void
  /** Xóa hẳn room đã xong; lỗi (vd. room vẫn đang chạy) thì ném ra để nơi gọi báo. */
  removeRequest: (requestId: string) => Promise<void>
  /** Dừng lượt chạy đang diễn ra của room; kết quả (room "không hoàn thành") về qua stream. */
  stopRequest: (requestId: string) => void
}

const StoreContext = createContext<Store | null>(null)

const nowTime = () => new Date().toTimeString().slice(0, 5)

// Gateway cắt stream sau 10 phút hoặc khi mạng rớt: đợi chút rồi mở lại, ai-service phát lại từ đầu.
const RETRY_MS = 3000

export function StoreProvider({ children }: { children: ReactNode }) {
  const [teams, setTeams] = useState<MockTeam[]>(seedTeams)
  const [rooms, setRooms] = useState<MockRoom[]>(seedRooms)
  const [activeRoomId, setActiveRoomId] = useState(seedRooms[0].id)

  const updateTeam = useCallback<Store['updateTeam']>(
    (id, patch) => setTeams((ts) => ts.map((t) => (t.id === id ? { ...t, ...patch } : t))),
    [],
  )
  const appendMessage = useCallback<Store['appendMessage']>(
    (roomId, msg) =>
      setRooms((rs) => rs.map((r) => (r.id === roomId ? { ...r, messages: [...r.messages, msg], updated: 'vừa xong' } : r))),
    [],
  )
  const createRoom = useCallback<Store['createRoom']>((title, agentIds) => {
    const id = `r${Date.now()}`
    const time = nowTime()
    const messages: MockMessage[] = agentIds.map((agentId, i) => ({
      id: `${id}-j${i}`, authorId: agentId, kind: 'text', time, body: `${agentById(agentId).name} đã tham gia cuộc trò chuyện`,
    }))
    setRooms((rs) => [{ id, title, agentIds, updated: 'vừa xong', messages }, ...rs])
    setActiveRoomId(id)
  }, [])

  // Room của người dùng (nhân viên lẫn admin) lưu ở ai-service (`/api/sessions`).
  const userId = useSession()?.user.id
  // Room của admin hiện như Claude Code: từng lượt gọi model, công cụ kèm tham số và kết quả
  const admin = useRole() === 'admin'
  const adminRef = useRef(admin)
  adminRef.current = admin
  const detailed = useRef(new Set<string>())
  const [requests, setRequests] = useState<StaffRequest[]>([])
  const [activeRequestId, setActiveRequestId] = useState('')

  useEffect(() => {
    setRequests([])
    setActiveRequestId('')
    detailed.current.clear()
    if (!userId) return
    let live = true
    listSessions()
      .then((ss) => { if (live) setRequests(ss.map(toRequest)) })
      .catch(() => { /* để trống: vẫn tạo được room mới */ })
    return () => { live = false }
  }, [userId])

  const patchRequest = (id: string, f: (r: StaffRequest) => StaffRequest) =>
    setRequests((rs) => rs.map((r) => (r.id === id ? f(r) : r)))
  const push = (r: StaffRequest, status: StaffRequest['status'], ...items: ThreadItem[]): StaffRequest =>
    ({ ...r, status, updated: nowTime(), items: [...r.items, ...items] })

  // Room của admin không chạy: dựng lại từ trace đã lưu. Bỏ qua nếu room đã chạy lại trong lúc chờ.
  const loadDetail = (id: string) => {
    detailed.current.add(id)
    getRoomDetail(Number(id))
      .then((d) => patchRequest(id, (r) => (r.status === 'running' ? r : { ...r, items: traceItems(d) })))
      .catch(() => { detailed.current.delete(id) /* giữ bản như nhân viên thấy */ })
  }
  // Room của admin xong lượt: giữ nguyên các tin live tới khi có trace đã lưu rồi thay một lần, thay vì
  // đổi sang bản nhân viên thấy rồi lại đổi tiếp (hai lần nhảy giao diện)
  const save = (id: string, s: Session) => {
    if (!adminRef.current || s.status === 'running') {
      patchRequest(id, () => toRequest(s))
      return
    }
    patchRequest(id, (r) => ({ ...toRequest(s), items: r.items }))
    detailed.current.add(id)
    getRoomDetail(Number(id))
      .then((d) => patchRequest(id, (r) => (r.status === 'running' ? r : { ...r, items: traceItems(d) })))
      .catch(() => patchRequest(id, () => toRequest(s)))
  }
  const activeRequest = requests.find((r) => r.id === activeRequestId)
  const openDetail = admin && activeRequest && activeRequest.status !== 'running' && !activeRequest.id.startsWith('tmp')
    ? activeRequest.id : ''
  useEffect(() => {
    if (openDetail && !detailed.current.has(openDetail)) loadDetail(openDetail)
  }, [openDetail])

  // Room đang chạy thì theo dõi qua SSE; mỗi room một kết nối, xong hoặc rớt thì đóng.
  const runningIds = requests.filter((r) => r.status === 'running' && !r.id.startsWith('tmp')).map((r) => r.id).join(',')
  const following = useRef(new Map<string, AbortController>())
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    for (const id of runningIds ? runningIds.split(',') : []) {
      if (following.current.has(id)) continue
      const ctrl = new AbortController()
      following.current.set(id, ctrl)
      // Mỗi event dựng lại cụm tin "live" từ đầu (thay cả dòng chờ `running` mà toRequest thêm vào)
      const received: Progress[] = []
      // Admin: các tin có trước lượt này, giữ từ event đầu. Tin của lượt dựng từ trace mang id giống bản
      // đã lưu, nên khi lượt xong React giữ nguyên chúng thay vì vẽ lại.
      let before: ThreadItem[] | null = null
      const onProgress = (progress: Progress) => {
        received.push(progress)
        patchRequest(id, (r) => {
          if (!adminRef.current) {
            return { ...r, items: [...r.items.filter((i) => i.id !== 'running' && !i.id.startsWith('live-')), ...liveItems(received)] }
          }
          before ??= r.items.filter((i) => i.id !== 'running' && !i.id.startsWith('live-'))
          // Số lượt như máy chủ đánh: mỗi yêu cầu, mỗi câu trả lời hỏi lại và mỗi agent mới được đồng ý mở
          // một lượt, lượt đầu là 0
          const run = before.filter((i) => i.kind === 'request' || (i.kind === 'clarify' && i.answer)
            || (i.kind === 'skill' && i.decision?.value === 'yes')).length - 1
          return { ...r, items: [...before, ...liveTraceItems(received, run)] }
        })
      }
      followSession(Number(id), onProgress, ctrl.signal)
        .then((s) => save(id, s))
        .catch(() => { /* rớt kết nối: thử lại bên dưới */ })
        .finally(() => {
          following.current.delete(id)
          // Còn running (rớt mạng, hay run không ở instance này) thì effect chạy lại và mở stream mới
          if (!ctrl.signal.aborted) setTimeout(() => setRetry((n) => n + 1), RETRY_MS)
        })
    }
  }, [runningIds, retry])
  // Đổi tài khoản hoặc rời app: đóng mọi stream đang mở
  useEffect(() => () => {
    following.current.forEach((c) => c.abort())
    following.current.clear()
  }, [userId])

  // Lỗi gọi API chỉ hiện trong room, không lưu: tải lại trang thì thấy đúng bản trên máy chủ.
  const fail = (id: string, err: unknown) => patchRequest(id, (r) => push(r, 'failed', {
    kind: 'failed', id: `${id}-${Date.now()}`, time: nowTime(), trace: [],
    body: err instanceof Error ? err.message : 'Không gửi được yêu cầu',
  }))

  const submitRequest = useCallback<Store['submitRequest']>((body) => {
    // Hiện room ngay với id tạm trong lúc AI chạy, có kết quả thì thay bằng session thật.
    const temp = `tmp${Date.now()}`
    const time = nowTime()
    const title = body.length > 48 ? `${body.slice(0, 48).trimEnd()}…` : body
    setRequests((rs) => [{
      id: temp, title, status: 'running', updated: time,
      items: [{ kind: 'request', id: `${temp}-1`, time, body }, { kind: 'route', id: 'running', time, body: 'Đang chọn agent phù hợp…' }],
    }, ...rs])
    setActiveRequestId(temp)
    createSession(body)
      .then((s) => {
        const saved = toRequest(s)
        setRequests((rs) => rs.map((r) => (r.id === temp ? saved : r)))
        setActiveRequestId((cur) => (cur === temp ? saved.id : cur))
      })
      .catch((err) => fail(temp, err))
  }, [])
  // Trả lời câu hỏi làm rõ (nút gợi ý hoặc gõ tay): yêu cầu chạy tiếp trên máy chủ. Room đã xong hoặc
  // lỗi thì đó là yêu cầu tiếp theo: Jev chọn agent lại, agent đọc ngữ cảnh các lượt trước.
  const reply = useCallback<Store['reply']>((requestId, body) => {
    const time = nowTime()
    const current = requests.find((r) => r.id === requestId)
    const pending = current && pendingItem(current)
    if (current && !pending && (current.status === 'done' || current.status === 'failed') && !requestId.startsWith('tmp')) {
      // Như câu trả lời bên dưới: giữ trạng thái cũ tới khi máy chủ nhận yêu cầu
      patchRequest(requestId, (r) => push(r, r.status,
        { kind: 'request', id: `${requestId}-${Date.now()}`, time, body },
        { kind: 'route', id: 'running', time, body: 'Đang chọn agent phù hợp…' }))
      messageSession(Number(requestId), body)
        .then((s) => save(requestId, s))
        .catch((err) => {
          patchRequest(requestId, (r) => ({ ...r, items: r.items.filter((i) => i.id !== 'running') }))
          fail(requestId, err)
        })
      return
    }
    if (pending?.kind !== 'clarify') {
      // Đang chờ duyệt: máy chủ chỉ nhận yêu cầu mới khi lượt này xong. Room id tạm chưa có trên máy chủ.
      patchRequest(requestId, (r) => push(r, r.status, {
        kind: 'route', id: `${requestId}-${Date.now()}`, time,
        body: pending ? 'Duyệt hoặc từ chối ở trên trước khi gửi yêu cầu tiếp.' : 'Room này chưa được tạo. Tạo Room mới để gửi lại yêu cầu.',
      }))
      return
    }
    // Hiện ngay câu trả lời (trong khung hỏi, không thành tin riêng) và Điều phối đang nghĩ, nhưng giữ
    // trạng thái cũ: room chỉ thành `running` khi máy chủ đã nhận câu trả lời. Đổi sớm thì stream mở
    // trước, đọc phải bản `waiting` cũ và đè lên.
    patchRequest(requestId, (r) => push(
      { ...r, items: r.items.map((i) => (i.kind === 'clarify' && !i.answer ? { ...i, answer: body } : i)) },
      r.status,
      { kind: 'message', id: 'running', time, agent: 'coordinator', body: [],
        status: { label: 'Thinking', since: new Date().toISOString() } },
    ))
    answerSession(Number(requestId), body)
      .then((s) => save(requestId, s))
      .catch((err) => fail(requestId, err))
  }, [requests])
  const decide = useCallback<Store['decide']>((requestId, itemId, value) => {
    const time = nowTime()
    patchRequest(requestId, (r) => ({
      ...r, items: r.items.map((i) => (i.id === itemId && (i.kind === 'approval' || i.kind === 'skill') ? { ...i, decision: { value, time } } : i)),
    }))
    decideSession(Number(requestId), value === 'yes')
      .then((s) => save(requestId, s))
      .catch((err) => fail(requestId, err))
  }, [])
  const removeRequest = useCallback<Store['removeRequest']>(async (requestId) => {
    await deleteSession(Number(requestId))
    setRequests((rs) => rs.filter((r) => r.id !== requestId))
    // Đang mở đúng room vừa xóa thì về màn Room mới
    setActiveRequestId((cur) => (cur === requestId ? '' : cur))
  }, [])
  const stopRequest = useCallback<Store['stopRequest']>((requestId) => {
    // 409: lượt chạy vừa xong trước khi kịp dừng; stream sẽ đưa kết quả về như thường
    stopSession(Number(requestId)).catch(() => {})
  }, [])

  const value = useMemo(
    () => ({
      teams, updateTeam, rooms, activeRoomId, setActiveRoomId, appendMessage, createRoom,
      requests, activeRequestId, setActiveRequestId, submitRequest, reply, decide, removeRequest, stopRequest,
    }),
    [teams, updateTeam, rooms, activeRoomId, appendMessage, createRoom, requests, activeRequestId, submitRequest, reply, decide,
      removeRequest, stopRequest],
  )
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore(): Store {
  const s = useContext(StoreContext)
  if (!s) throw new Error('useStore phải nằm trong StoreProvider')
  return s
}
