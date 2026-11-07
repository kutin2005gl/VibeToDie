import { ApiError, apiUrl } from './base'

// Khớp user-service (README, mục user-service).
export interface User {
  id: string
  email: string
  name: string
  departments: string[]
  created_at: string
}

// Token nằm trong cookie HttpOnly do server Next (BFF, src/server/bff.ts) quản lý: JS không đọc được
// token, chỉ biết người dùng nào đang đăng nhập.
export interface Session {
  user: User
}

/** `undefined`: chưa hỏi xong máy chủ; `null`: chưa đăng nhập. */
let session: Session | null | undefined = undefined
const listeners = new Set<() => void>()
const isBrowser = typeof window !== 'undefined'

// Tab khác đăng nhập hay đăng xuất thì tab này hỏi lại máy chủ.
const channel = isBrowser && 'BroadcastChannel' in window ? new BroadcastChannel('boa.session') : null
if (channel) channel.onmessage = () => void load()

function setSession(s: Session | null, broadcast = false) {
  session = s
  listeners.forEach((l) => l())
  if (broadcast) channel?.postMessage('changed')
}

let loading: Promise<void> | null = null

/** Hỏi máy chủ người dùng hiện tại; server tự làm mới token nếu cần. */
function load(): Promise<void> {
  loading ??= fetch(apiUrl('/api/users/me'), { cache: 'no-store' })
    .then(async (res) => setSession(res.ok ? { user: (await res.json()) as User } : null))
    .catch(() => setSession(null))
    .finally(() => {
      loading = null
    })
  return loading
}

export function getSession() {
  return session
}

/** Lúc render trên server chưa biết phiên. */
export function getServerSession() {
  return undefined
}

export function subscribe(listener: () => void) {
  listeners.add(listener)
  if (session === undefined) void load()
  return () => listeners.delete(listener)
}

async function post(path: string, body?: unknown): Promise<Response> {
  try {
    return await fetch(apiUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Không kết nối được tới máy chủ')
  }
}

export async function login(email: string, password: string): Promise<User> {
  const res = await post('/api/auth/login', { email, password })
  if (res.status === 401) throw new ApiError(401, 'Sai email hoặc mật khẩu')
  if (res.status === 429) throw new ApiError(429, 'Thử lại quá nhiều lần, vui lòng đợi một phút')
  if (!res.ok) throw new ApiError(res.status, `Đăng nhập thất bại (lỗi ${res.status})`)
  const { user } = (await res.json()) as Session
  setSession({ user }, true)
  return user
}

export async function logout() {
  setSession(null)
  // Server thu hồi phiên và xoá cookie; lỗi mạng ở đây không giữ người dùng lại ở trạng thái đăng nhập.
  await post('/api/auth/logout').catch(() => {})
  channel?.postMessage('changed')
}

/**
 * fetch tới BFF; cookie đi kèm tự động và server tự làm mới token. Vẫn gặp 401 thì hỏi lại máy chủ xem
 * phiên còn không (hết hạn hoặc bị thu hồi thì về màn đăng nhập).
 */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(apiUrl(path), init)
  if (res.status === 401 && session) void load()
  return res
}
