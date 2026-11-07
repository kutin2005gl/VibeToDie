import { NextResponse, type NextRequest } from 'next/server'

// BFF: trình duyệt chỉ giữ cookie HttpOnly, không bao giờ thấy token. Next đọc cookie, gắn
// `Authorization: Bearer` rồi chuyển request tới gateway. Chỉ chạy trên server (route handler).

export const GATEWAY_URL = (process.env.GATEWAY_URL ?? 'http://localhost:8080').replace(/\/+$/, '')

export const ACCESS_COOKIE = 'boa_at'
export const REFRESH_COOKIE = 'boa_rt'
// user-service không trả hạn của refresh token: khớp REFRESH_TOKEN_TTL mặc định (7 ngày).
const REFRESH_MAX_AGE = 7 * 24 * 60 * 60
// Cookie access hết hạn sớm hơn token một chút, nên request kế tiếp làm mới trước thay vì gặp 401.
const ACCESS_MARGIN = 30

export interface User {
  id: string
  email: string
  name: string
  departments: string[]
  created_at: string
}

interface Tokens {
  access_token: string
  expires_in: number
  refresh_token: string
  user: User
}

// Trình duyệt bỏ cookie `secure` trên trang http (ngoài localhost): đặt COOKIE_SECURE=false khi chạy sau HTTP thường.
const cookieSecure = process.env.COOKIE_SECURE ? process.env.COOKIE_SECURE === 'true' : process.env.NODE_ENV === 'production'

const cookieBase = {
  httpOnly: true,
  sameSite: 'lax' as const,
  secure: cookieSecure,
  path: '/',
}

export function setTokens(res: NextResponse, t: Tokens) {
  res.cookies.set(ACCESS_COOKIE, t.access_token, { ...cookieBase, maxAge: Math.max(t.expires_in - ACCESS_MARGIN, 1) })
  res.cookies.set(REFRESH_COOKIE, t.refresh_token, { ...cookieBase, maxAge: REFRESH_MAX_AGE })
}

export function clearTokens(res: NextResponse) {
  res.cookies.set(ACCESS_COOKIE, '', { ...cookieBase, maxAge: 0 })
  res.cookies.set(REFRESH_COOKIE, '', { ...cookieBase, maxAge: 0 })
}

export function refreshCookie(req: NextRequest) {
  return req.cookies.get(REFRESH_COOKIE)?.value
}

export function errorJson(status: number, error: string) {
  return NextResponse.json({ error }, { status })
}

/**
 * Chặn request ghi từ trang khác (CSRF). SameSite=Lax đã không gửi cookie theo POST khác site; đây là lớp
 * thứ hai. Trình duyệt luôn gửi `Origin` với request ghi; client không phải trình duyệt thì không có cookie.
 */
export function crossOrigin(req: NextRequest) {
  if (req.method === 'GET' || req.method === 'HEAD') return false
  const origin = req.headers.get('origin')
  if (!origin) return false
  const host = req.headers.get('x-forwarded-host') ?? req.headers.get('host')
  try {
    return new URL(origin).host !== host
  } catch {
    return true
  }
}

/** Header gửi tiếp cho gateway: giữ IP client (rate limit của gateway) và request id. */
function forwardHeaders(req: NextRequest) {
  const h = new Headers()
  for (const name of ['accept', 'content-type', 'idempotency-key', 'x-request-id', 'x-forwarded-for']) {
    const v = req.headers.get(name)
    if (v) h.set(name, v)
  }
  return h
}

/** Gọi user-service qua gateway (đăng nhập, làm mới, đăng xuất). */
export function postUsers(req: NextRequest, path: string, body: unknown) {
  const headers = forwardHeaders(req)
  headers.set('content-type', 'application/json')
  return fetch(`${GATEWAY_URL}/api/users${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    cache: 'no-store',
  })
}

export type Refreshed = Tokens | 'expired'

// Refresh token chỉ dùng được một lần: dùng lại thì user-service thu hồi cả phiên. Nhiều request cùng
// gặp token hết hạn nên gom về một lần làm mới, và giữ kết quả thêm một lúc cho các request đã gửi kèm
// cookie cũ. Chỉ đúng khi chạy một instance Next; nhiều instance thì cần kho dùng chung.
const refreshing = new Map<string, Promise<Refreshed>>()
const REFRESH_REUSE_MS = 30_000

export function refresh(req: NextRequest, token: string): Promise<Refreshed> {
  let p = refreshing.get(token)
  if (!p) {
    p = postUsers(req, '/refresh', { refresh_token: token }).then(async (res) => {
      if (res.status === 401) return 'expired' as const
      // Lỗi khác (5xx, mạng) thì ném: giữ cookie để lần sau thử lại.
      if (!res.ok) throw new Error(`refresh ${res.status}`)
      return (await res.json()) as Tokens
    })
    refreshing.set(token, p)
    p.catch(() => {}).finally(() => setTimeout(() => refreshing.delete(token), REFRESH_REUSE_MS))
  }
  return p
}

// Header theo từng kết nối hoặc đã mất nghĩa vì fetch đã giải nén body.
const dropResponseHeaders = ['connection', 'content-encoding', 'content-length', 'keep-alive', 'transfer-encoding', 'set-cookie']

/**
 * Chuyển request tới gateway kèm access token. Không có access token (cookie đã hết hạn) hoặc gateway trả
 * 401 thì làm mới một lần rồi gửi lại. Body trả về được stream nguyên dạng nên SSE vẫn chạy.
 */
export async function proxy(req: NextRequest, path: string): Promise<NextResponse> {
  const token = refreshCookie(req)
  let access = req.cookies.get(ACCESS_COOKIE)?.value
  let renewed: Refreshed | undefined

  const renew = async () => {
    if (!token || renewed) return
    renewed = await refresh(req, token).catch(() => undefined)
    access = renewed && renewed !== 'expired' ? renewed.access_token : undefined
  }

  // Body JSON của app nhỏ: đọc hết một lần để gửi lại được sau khi làm mới token.
  const body = req.method === 'GET' || req.method === 'HEAD' ? undefined : await req.arrayBuffer()
  const send = () => {
    const headers = forwardHeaders(req)
    if (access) headers.set('authorization', `Bearer ${access}`)
    return fetch(`${GATEWAY_URL}${path}${req.nextUrl.search}`, {
      method: req.method,
      headers,
      body,
      cache: 'no-store',
      redirect: 'manual',
      // Trình duyệt đóng stream thì đóng luôn kết nối tới gateway.
      signal: req.signal,
    })
  }

  let upstream: Response
  try {
    if (!access) await renew()
    upstream = await send()
    if (upstream.status === 401 && token && !renewed) {
      await upstream.body?.cancel()
      await renew()
      upstream = await send()
    }
  } catch {
    return errorJson(502, 'gateway unreachable')
  }

  const headers = new Headers(upstream.headers)
  dropResponseHeaders.forEach((h) => headers.delete(h))
  const res = new NextResponse(upstream.body, { status: upstream.status, headers })
  if (renewed === 'expired') clearTokens(res)
  else if (renewed) setTokens(res, renewed)
  return res
}
