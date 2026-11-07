import { authFetch } from './auth'
import { ApiError } from './base'
import { agentCatalog } from '../mocks/agentCatalog'
import type { MessageStatus, ParallelMember, StaffRequest, ThreadItem } from '../mocks/staff'
import { parseSse } from './stream'

// Khớp ai-service `/api/sessions` (README, mục ai-service); gateway giữ nguyên đường dẫn.
export interface PendingAction {
  id: string
  name: string
  arguments: Record<string, unknown>
  /** Chỉ có sau khi duyệt: `sending` còn lại nghĩa là chưa rõ đã gửi chưa, cần kiểm tra tay. */
  status?: 'sending' | 'done' | 'failed'
  error?: string
}

export type SessionItem = { id: string; at: string } & (
  | { kind: 'request' | 'reply'; body: string }
  | { kind: 'route'; agent: string; branch: string }
  | { kind: 'clarify'; question: string; answer?: string }
  | { kind: 'result'; agent: string; output: string; result: Record<string, unknown>; trace?: TraceCall[] }
  | { kind: 'approval'; actions: PendingAction[]; decision?: { value: 'yes' | 'no'; at: string } }
  // Agent Factory soạn, đã qua kiểm tra của code; chưa chạy cho tới khi nhân viên đồng ý
  | {
      kind: 'agent_proposal'; agent_id: number; name: string; description: string; tools: string[]; summary: string
      decision?: { value: 'yes' | 'no'; at: string }
    }
  | { kind: 'failed'; body: string; trace?: TraceCall[] }
)

/** Một lần gọi công cụ trong lượt chạy; `ok: false` khi công cụ trả lỗi. */
type TraceCall = { agent: string; name: string; ok: boolean }

export interface Session {
  id: number
  title: string
  provider: string
  status: StaffRequest['status']
  items: SessionItem[]
  created_at: string
  updated_at: string
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await authFetch(`/api/sessions${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, 'Không kết nối được tới máy chủ')
  }
  const body = await res.json().catch(() => ({}))
  if (res.ok) return body as T
  if (res.status === 429) throw new ApiError(429, 'Gửi quá nhiều yêu cầu, vui lòng đợi một phút')
  throw new ApiError(res.status, typeof body.detail === 'string' ? body.detail : `Lỗi ${res.status}`)
}

export function listSessions() {
  return call<Session[]>('')
}

/** Agent riêng của tài khoản: Factory soạn, nhân viên đã đồng ý dùng. */
export interface MyAgent {
  id: number
  name: string
  /** Điều kiện định tuyến "Use when … Not for …", viết cho Jev (tiếng Anh) */
  description: string
  role: string
  tools: string[]
  approved_at: string | null
}

export function getSession(id: number) {
  return call<Session>(`/${id}`)
}

/** Trả về ngay với `status: running`; AI chạy nền, gọi lại getSession để lấy kết quả. */
export function createSession(text: string) {
  return call<Session>('', { method: 'POST', body: JSON.stringify({ text }) })
}

export function answerSession(id: number, answer: string) {
  return call<Session>(`/${id}/answer`, { method: 'POST', body: JSON.stringify({ answer }) })
}

// Lý do 409 do máy chủ ghi (ai/app/services/sessions.py), nói lại cho nhân viên
const notAccepted: Record<string, string> = {
  'room is full: start a new room': 'Room đã đủ số lượt. Tạo Room mới để gửi tiếp.',
  'session is not ready for a new request': 'Room đang chạy hoặc chờ bạn duyệt. Đợi xong rồi gửi tiếp.',
}

/** Yêu cầu tiếp theo trong room đã xong hoặc lỗi; như createSession, AI chạy nền với ngữ cảnh các lượt trước. */
export function messageSession(id: number, text: string) {
  return call<Session>(`/${id}/messages`, { method: 'POST', body: JSON.stringify({ text }) }).catch((err) => {
    throw err instanceof ApiError && err.status === 409 && notAccepted[err.message]
      ? new ApiError(409, notAccepted[err.message]) : err
  })
}

/** Dừng lượt chạy đang diễn ra; room được lưu là "không hoàn thành" và stream nhận nó ngay sau đó. */
export function stopSession(id: number) {
  return call<void>(`/${id}/stop`, { method: 'POST' })
}

/** Xóa hẳn room đã xong (máy chủ trả 409 nếu room còn đang chạy). */
export function deleteSession(id: number) {
  return call<void>(`/${id}`, { method: 'DELETE' })
}

export function decideSession(id: number, approve: boolean) {
  return call<Session>(`/${id}/decision`, { method: 'POST', body: JSON.stringify({ approve }) })
}

// Tên hiển thị lấy từ danh mục agent (cùng chỗ với màu và icon) để mọi màn gọi agent giống nhau.
const agentLabel = (id: string) => agentCatalog.find((a) => a.id === id)?.name ?? id
/** Tên hành động cần duyệt cho nhân viên; tool chưa có tên thì hiện tên gốc. */
const actionTitle: Record<string, string> = { send_email: 'Gửi email cho khách?' }

// Khóa claim trong ngoặc như [order_id, paid_amount] là để code đối chiếu, không dành cho nhân viên.
const claimRefs = /\s*\[[a-z][a-z0-9_]*(?:,\s*[a-z][a-z0-9_]*)*\]/g
const plain = (s: string) => s.replace(claimRefs, '').replace(/\*\*/g, '').trim()

/** Chữ trong một mảng: chuỗi, hoặc trường `text`/`action` của object (findings, proposed_actions...). */
function texts(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v
    .map((x) => (typeof x === 'string' ? x : typeof x?.text === 'string' ? x.text : typeof x?.action === 'string' ? x.action : ''))
    .map(plain)
    .filter(Boolean)
}

const lines = (s: string) => s.split(/\n+/).map((l) => plain(l.replace(/^\s*[-*]\s+/, '• '))).filter(Boolean)

const bullets = (items: string[], heading?: string) =>
  items.length ? [...(heading ? [heading] : []), ...items.map((t) => `• ${t}`)] : []

/**
 * Tin trả lời của một agent, dựng từ `result` (final_answer đã kiểm tra) thay vì `output`:
 * `output` là bản text cho client chỉ đọc chữ, còn lẫn khóa claim và trường thô.
 * Nhân viên thấy ngay câu trả lời và việc cần làm; các phát hiện chi tiết gập trong "Chi tiết".
 */
type Answer = { body: string[]; drafts: { title: string; body: string }[]; details: string[] }

/** Bản nháp agent soạn (email, tin nhắn cho khách hay nội bộ), để nhân viên đọc trước khi gửi. */
function draftsOf(r: Record<string, unknown>): Answer['drafts'] {
  if (!Array.isArray(r.drafts)) return []
  return r.drafts
    .filter((d) => typeof d?.body === 'string' && d.body.trim())
    .map((d) => ({
      title: [d.audience === 'customer' ? 'Gửi khách' : 'Nội bộ', d.channel, d.subject].filter(Boolean).join(' · '),
      body: d.body,
    }))
}

export function answerParts(r: Record<string, unknown>, output: string): Answer {
  // knowledge trả `answer`, Coordinator trả `final_response`, worker khác trả `summary`
  const lead = [r.answer, r.final_response, r.summary].find((v): v is string => typeof v === 'string' && v.trim() !== '')
  if (!lead) return { body: lines(output), drafts: [], details: [] }
  const advice = typeof r.recommendation === 'string' ? [plain(r.recommendation)].filter(Boolean) : []
  return {
    body: [
      ...lines(lead),
      ...bullets(texts(r.open_questions), 'Cần xác nhận:'),
      ...bullets([...advice, ...texts(r.proposed_actions)], 'Đề xuất:'),
    ],
    drafts: draftsOf(r),
    details: [...bullets(texts(r.findings)), ...bullets(texts(r.instructions))],
  }
}

type PlanStep = { id: string; agent: string; label?: string }
type Review = { decision: string; note?: string | null; seconds?: number }
// Một lần agent trả lời (đã qua code) và nhận xét của Điều phối về lần đó
type StepAnswer = { result: Record<string, unknown>; seconds?: number; review: Review | null }
type StepRecord = {
  id: string; agent: string; status: string; result?: Record<string, unknown> | null; seconds?: number; answers?: StepAnswer[]
}
type Replan = { plan: { steps: PlanStep[] }; steps?: StepRecord[] }

const NOT_DONE = 'Chưa hoàn thành phần việc này.'
// Jev (bộ định tuyến, không phải một agent) chưa chọn xong: chưa ai làm, nên không gắn avatar nào
const ROUTING = 'Đang chọn agent phù hợp…'
// Lý do kết thúc do chính máy chủ ghi (ai/app/store/sessions.py), nói lại cho nhân viên
const STOPPED = 'run stopped by staff'
const failedText: Record<string, string> = {
  [STOPPED]: 'Bạn đã dừng lượt chạy này.',
  'run interrupted: ai-service restarted': 'Lượt chạy bị ngắt vì hệ thống khởi động lại. Gửi lại yêu cầu.',
  'run ended without saving its result': 'Lượt chạy kết thúc nhưng không lưu được kết quả. Gửi lại yêu cầu.',
}
const REPLANNED = 'Một phần chưa làm được, lập lại kế hoạch cho phần còn lại.'
// Mandate gộp các lượt cũ của room (ai/app/mandates/compactor.md); không phải agent nhân viên làm việc cùng
const COMPACTOR = 'compactor'

const worked = (seconds: number | undefined): MessageStatus | undefined =>
  seconds === undefined ? undefined : { label: 'Worked', seconds }

const secondsBetween = (from?: string, to?: string) =>
  from && to ? Math.max(0, (Date.parse(to) - Date.parse(from)) / 1000) : undefined

export function planMessage(id: string, at: string, steps: PlanStep[], seconds?: number): ThreadItem {
  return { kind: 'message', id, time: clock(at), at, agent: 'coordinator', body: [], status: worked(seconds),
    mentions: steps.map((s) => ({ agent: s.agent, text: s.label ?? '' })) }
}

// Trả lời của một step gửi lại Điều phối: tóm tắt, bản nháp nếu có, phát hiện trong "Chi tiết".
// Câu hỏi còn mở của từng step không hiện ở đây: Điều phối gom chúng vào kết luận.
export function stepReply(id: string, at: string, agent: string, result: Record<string, unknown> | null, seconds?: number): ThreadItem {
  const base = { kind: 'message' as const, id, time: clock(at), at, agent, to: 'coordinator', status: worked(seconds) }
  const summary = result?.summary
  if (typeof summary !== 'string' || !summary.trim()) return { ...base, body: [NOT_DONE] }
  return { ...base, body: lines(summary), drafts: draftsOf(result!), details: bullets(texts(result!.findings)) }
}

// Khi Điều phối không viết `note` (máy chủ cũ, model bỏ trống) thì nói theo quyết định
const REVIEWED: Record<string, string> = {
  accept: 'Đã duyệt.',
  retry: 'Cần làm lại phần này.',
  replan: 'Phần này cần lập lại kế hoạch.',
  clarify: 'Cần hỏi thêm bạn trước khi làm tiếp.',
}

// Điều phối trả lời lại agent sau khi duyệt: @agent kèm nhận xét
export function reviewMessage(id: string, at: string, agent: string, review: Review): ThreadItem {
  const note = typeof review.note === 'string' && review.note.trim() ? lines(review.note) : []
  return { kind: 'message', id, time: clock(at), at, agent: 'coordinator', to: agent,
    body: note.length ? note : [REVIEWED[review.decision] ?? REVIEWED.accept], status: worked(review.seconds) }
}

/**
 * Các tin của một step theo đúng thứ tự đã xảy ra: mỗi câu trả lời của agent rồi nhận xét của Điều
 * phối; làm lại thì là tin mới ở dưới, không thay tin cũ, để nhân viên thấy trọn quá trình.
 */
const replies = (prefix: string, at: string, steps: StepRecord[] = []) =>
  steps.flatMap((s): ThreadItem[] => {
    const answers = s.answers ?? []
    // Phiên cũ (chưa lưu `answers`) hoặc không lần nào qua được code: một tin như trước
    if (!answers.length) return [stepReply(`${prefix}-${s.id}`, at, s.agent, s.status === 'accepted' ? s.result ?? null : null, s.seconds)]
    const out = answers.flatMap((a, n): ThreadItem[] => [
      stepReply(`${prefix}-${s.id}-${n}`, at, s.agent, a.result, a.seconds),
      ...(a.review ? [reviewMessage(`${prefix}-${s.id}-${n}-review`, at, s.agent, a.review)] : []),
    ])
    // Bị yêu cầu làm lại nhưng lần làm lại không qua được code tới hết lượt
    if (s.status === 'failed' && answers[answers.length - 1].review?.decision === 'retry') {
      out.push(stepReply(`${prefix}-${s.id}-end`, at, s.agent, null))
    }
    return out
  })

/**
 * Kết quả của một lượt chạy thành chuỗi tin như một nhóm chat: Coordinator giao từng phần cho agent
 * (@agent), mỗi agent trả lời lại Coordinator, rồi Coordinator kết luận. Kế hoạch bị bỏ (lập lại)
 * vẫn hiện, kèm phần nó đã làm. Một agent làm một mình thì chỉ có tin của agent đó. Công cụ đã gọi
 * và các lần bị từ chối không hiện cho nhân viên. `startedAt`: lúc gửi yêu cầu, để tính tổng thời gian.
 */
function chain(i: Extract<SessionItem, { kind: 'result' }>, startedAt?: string): ThreadItem[] {
  const r = i.result
  const answer = { ...answerParts(r, i.output), status: worked(secondsBetween(startedAt, i.at)) }
  const final = (agent: string): ThreadItem => ({ kind: 'message', id: i.id, time: clock(i.at), at: i.at, agent, ...answer })
  const plan = r.plan as { steps: PlanStep[] } | null | undefined
  if (i.agent !== 'coordinator' || !plan) {
    // Không agent nào chạy (chưa có quyền, nhánh chưa nối): đó là thông báo của hệ thống
    return [final(Object.keys(r).length === 0 ? 'coordinator' : i.agent)]
  }
  const dropped = ((r.replans ?? []) as Replan[]).flatMap((rp, n): ThreadItem[] => [
    planMessage(`${i.id}-old${n}-plan`, i.at, rp.plan.steps),
    ...replies(`${i.id}-old${n}`, i.at, rp.steps),
    { kind: 'message', id: `${i.id}-old${n}`, time: clock(i.at), at: i.at, agent: 'coordinator', body: [REPLANNED] },
  ])
  return [
    ...dropped,
    planMessage(`${i.id}-plan`, i.at, plan.steps),
    ...replies(i.id, i.at, (r.steps ?? []) as StepRecord[]),
    final('coordinator'),
  ]
}

/** Giờ nếu là hôm nay, còn lại ngày/tháng. */
export function clock(iso: string) {
  const d = new Date(iso)
  return d.toDateString() === new Date().toDateString()
    ? d.toTimeString().slice(0, 5)
    : d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })
}

export function toItems(i: SessionItem, startedAt?: string): ThreadItem[] {
  const time = clock(i.at)
  switch (i.kind) {
    case 'request':
      return [{ kind: i.kind, id: i.id, time, body: i.body }]
    case 'reply':
      // Câu trả lời cho câu hỏi làm rõ (máy chủ chỉ nhận loại này) đã hiện trong khung hỏi, như Claude Code
      return []
    case 'route':
      return [{ kind: 'route', id: i.id, time, body: `Chuyển cho ${agentLabel(i.agent)}` }]
    case 'clarify':
      return [{ kind: 'clarify', id: i.id, time, question: i.question, options: [], answer: i.answer }]
    case 'result':
      return chain(i, startedAt)
    case 'approval': {
      // Thẻ duyệt của UI dựng cho email khách; lấy các trường đó từ tham số nếu hành động có.
      const args = Object.assign({}, ...i.actions.map((a) => a.arguments)) as Record<string, unknown>
      const text = (v: unknown) => (v == null ? '' : typeof v === 'string' ? v : JSON.stringify(v))
      return [{
        kind: 'approval', id: i.id, time,
        title: i.actions.map((a) => actionTitle[a.name] ?? a.name).join(', '),
        facts: i.actions.flatMap((a) => Object.entries(a.arguments).map(([k, v]): [string, string] => [k, text(v)])),
        email: { to: text(args.to ?? args.email), subject: text(args.subject), body: text(args.body) },
        decision: i.decision && { value: i.decision.value, time: clock(i.decision.at) },
        // Một hành động lỗi hay chưa rõ là cả thẻ chưa xong
        sent: i.actions.some((a) => a.status === 'failed') ? 'failed'
          : i.actions.some((a) => a.status === 'sending') ? 'sending'
          : i.actions.length > 0 && i.actions.every((a) => a.status === 'done') ? 'done' : undefined,
      }]
    }
    case 'agent_proposal':
      // `description` là điều kiện định tuyến viết cho Jev (tiếng Anh); nhân viên đọc tóm tắt của Factory
      return [{
        kind: 'skill', id: i.id, time, name: i.name, summary: i.summary, tools: i.tools,
        checks: ['Đúng định dạng agent', 'Chỉ dùng công cụ bạn đã có quyền'],
        decision: i.decision && { value: i.decision.value, time: clock(i.decision.at) },
      }]
    case 'failed':
      // Trace (công cụ, các lần bị từ chối) vẫn lưu ở máy chủ cho màn quản trị, nhân viên không cần
      return [{ kind: 'failed', id: i.id, time, body: failedText[i.body] ?? i.body, trace: [], stopped: i.body === STOPPED }]
  }
}

export function toRequest(s: Session): StaffRequest {
  // Mỗi lượt chạy tính giờ từ lúc gửi yêu cầu, câu trả lời hoặc đồng ý agent mới gần nhất
  let startedAt: string | undefined
  const items = s.items.flatMap((i) => {
    const out = toItems(i, i.kind === 'request' || i.kind === 'reply' ? (startedAt = i.at) : startedAt)
    if (i.kind === 'agent_proposal' && i.decision?.value === 'yes') startedAt = i.decision.at
    return out
  })
  // Máy chủ chưa lưu gì trong lúc chạy: dòng chờ cho tới khi có tiến độ (cả sau khi tải lại trang).
  // Câu trả lời cho câu hỏi làm rõ và agent vừa duyệt luôn về Điều phối; yêu cầu mới thì Jev còn đang chọn agent.
  if (s.status === 'running') {
    const time = clock(s.updated_at)
    const last = s.items[s.items.length - 1]?.kind
    items.push(last === 'reply' || last === 'agent_proposal'
      ? { kind: 'message', id: 'running', time, agent: 'coordinator', body: [],
          status: { label: 'Thinking', since: startedAt ?? s.updated_at } }
      : { kind: 'route', id: 'running', time, body: ROUTING })
  }
  return { id: String(s.id), title: s.title, status: s.status, updated: clock(s.updated_at), items }
}

// Tiến độ của lượt chạy, đúng dạng event SSE của ai-service `/run` (README, mục ai-service).
// `at`: lúc máy chủ phát event (SSE của session có, SSE của `/run` thì không).
// `step_id`: event của một agent trong step của Điều phối; các step chạy cùng lúc nên event xen kẽ nhau.
type Stamped<T> = T & { at?: string }
export type Progress =
  | { event: 'route'; data: Stamped<{ branch: string; target: string }> }
  | { event: 'step'; data: Stamped<{ agent: string; step: number; max_steps: number; step_id?: string }> }
  | { event: 'tool_call'; data: Stamped<{ agent: string; step: number; id: string; name: string; step_id?: string }> }
  | { event: 'tool_result'; data: Stamped<{ agent: string; step: number; id: string; is_error: boolean; step_id?: string }> }
  | { event: 'phase'; data: Stamped<{ phase: 'plan' | 'review' | 'finalize' }> }
  | { event: 'plan'; data: Stamped<{ steps: PlanStep[] }> }
  | { event: 'step_started'; data: Stamped<{ id: string; agent: string; label?: string; task?: string; depends_on?: string[] }> }
  | { event: 'step_done'; data: Stamped<{
      id: string; agent: string; summary: string | null; result?: Record<string, unknown>; seconds?: number
    }> }
  | { event: 'step_reviewed'; data: Stamped<{ id: string; agent: string } & Review> }
  | { event: 'step_accepted'; data: Stamped<{ id: string; agent: string; summary: string | null; seconds?: number }> }
  | { event: 'step_failed'; data: Stamped<{ id: string; agent: string; reason?: string; seconds?: number }> }
  | { event: 'step_skipped'; data: Stamped<{ id: string; agent: string; reason: string }> }

/**
 * Theo dõi session qua SSE: mọi event của lượt chạy hiện tại (từ đầu), rồi session đã lưu.
 * `fetch` thay vì `EventSource` vì cần gửi `Authorization`. Đóng kết nối không dừng lượt chạy.
 */
export async function followSession(id: number, onProgress: (e: Progress) => void, signal: AbortSignal): Promise<Session> {
  const res = await authFetch(`/api/sessions/${id}/events`, { headers: { Accept: 'text/event-stream' }, signal })
  if (!res.ok || !res.body) throw new ApiError(res.status, `Lỗi ${res.status}`)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    const parsed = parseSse(buffer + value)
    buffer = parsed.rest
    for (const e of parsed.events) {
      if (e.event === 'session') return e.data as Session
      onProgress(e as Progress)
    }
  }
  throw new ApiError(0, 'Kết nối bị ngắt trước khi có kết quả')
}

/**
 * Chuỗi tin trong lúc chạy, dựng từ tiến độ đã nhận: kế hoạch của Điều phối, câu trả lời của từng
 * agent khi được chấp nhận, và ai đang làm gì (Thinking/Reviewing/Working, đồng hồ chạy từ `at` của
 * máy chủ nên tải lại trang vẫn đúng). Công cụ và từng lượt gọi model không hiện.
 * Các step chạy cùng lúc gom vào một khung song song (`parallel`), mỗi agent một thẻ với đồng hồ riêng;
 * Điều phối đang lập plan hay duyệt thì vẫn có dòng riêng ở cuối.
 * Id bắt đầu bằng `live-` để thay cả cụm mỗi khi có event mới.
 */
export function liveItems(received: Progress[]): ThreadItem[] {
  const items: ThreadItem[] = []
  // Điều phối, hoặc agent Jev giao thẳng, đang làm gì; agent trong step của Điều phối nằm ở `running`
  let active: { agent: string; label: MessageStatus['label']; since: string } | null = null
  let planningSince: string | undefined
  const stepSince: Record<string, string> = {}
  // Nhãn của từng step trong plan, để thẻ song song nói agent đang làm việc gì
  const labels: Record<string, string> = {}
  // Step đang làm, theo thứ tự bắt đầu
  const running = new Map<string, { agent: string; since: string }>()
  // Khung song song đang mở: mở khi step thứ hai bắt đầu lúc step trước chưa xong, đóng khi mọi thẻ đã xong
  let group: ParallelMember[] | null = null
  const member = (stepId: string) => group?.find((m) => m.id === stepId)
  const newMember = (stepId: string, agent: string, since: string): ParallelMember =>
    ({ id: stepId, agent, label: labels[stepId] ?? agentLabel(agent), state: 'working', since })
  const start = (stepId: string, agent: string, at: string, id: string) => {
    running.set(stepId, { agent, since: at })
    const m = member(stepId)
    if (m) {
      // Bị trả lại để làm lại: cùng thẻ, đồng hồ chạy lại
      Object.assign(m, { state: 'working', since: at, seconds: undefined })
    } else if (group) {
      group.push(newMember(stepId, agent, at))
    } else if (running.size > 1) {
      group = [...running].map(([sid, r]) => newMember(sid, r.agent, r.since))
      items.push({ kind: 'parallel', id, time: clock(group[0].since), members: group })
    }
  }
  const ended = (stepId: string, state: 'done' | 'failed', at: string, seconds?: number) => {
    running.delete(stepId)
    const m = member(stepId)
    if (m) Object.assign(m, { state, seconds: seconds ?? secondsBetween(m.since, at) })
    // Mọi thẻ đã xong: khung đứng lại như bản ghi, step sau mở khung mới
    if (group && !group.some((x) => x.state === 'working')) group = null
  }
  // Step đã có câu trả lời hiện ra, và quyết định duyệt gần nhất của từng step
  const answered = new Set<string>()
  const lastReview: Record<string, string> = {}
  let reviewSince: string | undefined
  // Agent Jev chọn; null khi Jev chưa định tuyến xong
  let routed: string | null = null
  let lastAt = new Date().toISOString()
  received.forEach((e, n) => {
    const at = e.data.at ?? lastAt
    lastAt = at
    const id = `live-${n}`
    const time = clock(at)
    switch (e.event) {
      case 'route':
        items.push({ kind: 'route', id, time, body: `Chuyển cho ${agentLabel(e.data.target)}` })
        // Agent được chọn bắt đầu ngay, kể cả trước lượt gọi model đầu tiên của nó
        routed = e.data.target
        active = { agent: e.data.target, label: e.data.target === 'coordinator' ? 'Thinking' : 'Working', since: at }
        break
      case 'phase':
        // Câu trả lời cho câu hỏi làm rõ đi thẳng tới Điều phối, không qua Jev
        routed = 'coordinator'
        if (e.data.phase === 'plan') planningSince = at
        if (e.data.phase === 'review') reviewSince = at
        active = { agent: 'coordinator', label: e.data.phase === 'review' ? 'Reviewing' : 'Thinking', since: at }
        break
      case 'step':
        // Agent trong step của Điều phối đã có thẻ hoặc dòng riêng từ step_started
        if (e.data.step_id) break
        // Agent Jev giao thẳng (không qua Điều phối) không có step_started: lượt gọi model đầu là lúc bắt đầu.
        // `compactor` tóm tắt các lượt cũ trước khi Jev chọn agent: nhân viên vẫn thấy dòng đang chọn agent.
        if (e.data.agent !== 'coordinator' && e.data.agent !== COMPACTOR && active?.agent !== e.data.agent) {
          active = { agent: e.data.agent, label: 'Working', since: at }
        }
        break
      case 'plan':
        for (const s of e.data.steps) if (s.label) labels[s.id] = s.label
        items.push(planMessage(id, at, e.data.steps, secondsBetween(planningSince, at)))
        active = null
        break
      case 'step_started':
        stepSince[e.data.id] = at
        if (e.data.label) labels[e.data.id] = e.data.label
        start(e.data.id, e.data.agent, at, id)
        active = null
        break
      case 'step_done':
        // Agent xong và đã qua code: hiện cả câu trả lời (kể cả bản nháp) ngay, trong lúc Điều phối
        // duyệt. Làm lại thì là một tin mới ở dưới.
        answered.add(e.data.id)
        items.push(stepReply(id, at, e.data.agent, e.data.result ?? { summary: e.data.summary },
          e.data.seconds ?? secondsBetween(stepSince[e.data.id], at)))
        ended(e.data.id, 'done', at, e.data.seconds)
        active = null
        break
      case 'step_reviewed':
        lastReview[e.data.id] = e.data.decision
        items.push(reviewMessage(id, at, e.data.agent, { ...e.data, seconds: e.data.seconds ?? secondsBetween(reviewSince, at) }))
        // Bị trả lại thì agent làm lại ngay, không có step_started mới
        if (e.data.decision === 'retry') start(e.data.id, e.data.agent, at, id)
        active = null
        break
      case 'step_accepted':
        // Máy chủ cũ không có step_done: câu trả lời đến lúc được chấp nhận
        if (!answered.has(e.data.id)) {
          items.push(stepReply(id, at, e.data.agent, { summary: e.data.summary },
            e.data.seconds ?? secondsBetween(stepSince[e.data.id], at)))
          ended(e.data.id, 'done', at, e.data.seconds)
        }
        active = null
        break
      case 'step_failed':
        // Điều phối đã nói phần này phải lập lại kế hoạch; còn lại là hết lượt mà không qua được code
        if (lastReview[e.data.id] !== 'replan') {
          items.push(stepReply(id, at, e.data.agent, null, e.data.seconds ?? secondsBetween(stepSince[e.data.id], at)))
        }
        ended(e.data.id, 'failed', at, e.data.seconds)
        active = null
        break
      case 'step_skipped':
        items.push({ kind: 'route', id, time, body: `Bỏ qua: ${labels[e.data.id] ?? agentLabel(e.data.agent)} (bước trước nó không thành công)` })
        break
    }
  })
  if (!active && !routed) {
    // Cùng id với dòng chờ của toRequest và của room vừa gửi, để dòng này không bị vẽ lại mỗi lần thay
    items.push({ kind: 'route', id: 'running', time: clock(lastAt), body: ROUTING })
    return items
  }
  // Agent làm một mình (không trong khung song song): dòng đang làm như trước
  if (!group) {
    for (const [stepId, r] of running) {
      items.push({ kind: 'message', id: `live-working-${stepId}`, time: clock(r.since), at: r.since, agent: r.agent,
        body: [], status: { label: 'Working', since: r.since } })
    }
  }
  // Giữa hai mốc (vd. vừa duyệt xong, chưa giao phần sau) và không agent nào đang làm là Điều phối đang nghĩ
  const now = active ?? (running.size ? null : { agent: 'coordinator', label: 'Thinking' as const, since: lastAt })
  if (now) {
    items.push({ kind: 'message', id: 'live-active', time: clock(now.since), at: now.since, agent: now.agent, body: [],
      status: { label: now.label, since: now.since } })
  }
  return items
}
