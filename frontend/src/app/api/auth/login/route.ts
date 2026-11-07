import { NextResponse, type NextRequest } from 'next/server'
import { crossOrigin, errorJson, postUsers, setTokens } from '../../../../server/bff'

// Đăng nhập qua user-service; token vào cookie HttpOnly, trình duyệt chỉ nhận thông tin người dùng.
export async function POST(req: NextRequest) {
  if (crossOrigin(req)) return errorJson(403, 'cross-origin request')
  const body = await req.json().catch(() => ({}))
  let res: Response
  try {
    res = await postUsers(req, '/login', body)
  } catch {
    return errorJson(502, 'gateway unreachable')
  }
  if (!res.ok) return new NextResponse(res.body, { status: res.status, headers: { 'content-type': 'application/json' } })
  const tokens = await res.json()
  const out = NextResponse.json({ user: tokens.user }, { headers: { 'cache-control': 'no-store' } })
  setTokens(out, tokens)
  return out
}
